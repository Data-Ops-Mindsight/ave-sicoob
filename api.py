"""Cliente Mindsight: token, paginação (segue `next`) e retry com backoff."""
from __future__ import annotations
import json
import time
import requests
from config import cfg, segredo, caminho_arquivo


def _token_fixo() -> str | None:
    return segredo("MINDSIGHT_TOKEN")


def _prov() -> dict:
    return cfg().get("token_provider") or {}


def provedor_ativo() -> bool:
    credencial = segredo("GOOGLE_CREDENTIALS_JSON") or segredo("GOOGLE_CREDENTIALS_PATH")
    return bool(_prov().get("ativo")) and bool(credencial) and bool(segredo("TOKEN_SPREADSHEET_ID"))


_cache = {"token": None, "ate": 0.0}
_info = {"origem": "—", "erro_planilha": None}


def _limpar(t: str) -> str:
    """Remove aspas/espaços e um prefixo "Token "/"Bearer " que venha junto na planilha."""
    t = str(t).strip().strip('"').strip("'").strip()
    for pre in ("token ", "bearer "):
        if t.lower().startswith(pre):
            t = t[len(pre):].strip()
    return t
ESCOPO = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def _servico_sheets():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    conteudo = segredo("GOOGLE_CREDENTIALS_JSON")
    if conteudo:
        cred = Credentials.from_service_account_info(json.loads(conteudo, strict=False), scopes=ESCOPO)
    else:
        cred = Credentials.from_service_account_file(str(caminho_arquivo(segredo("GOOGLE_CREDENTIALS_PATH"))), scopes=ESCOPO)
    return build("sheets", "v4", credentials=cred, cache_discovery=False)


def _buscar_na_planilha() -> str:
    """Lê a planilha (colunas cliente, sistema, token) e devolve o token do tenant/sistema configurados.
    As mensagens de erro não incluem id da planilha, caminho das credenciais nem token."""
    c = _prov()
    tenant = str(cfg()["tenant"]).strip().lower()
    sistema = str(c.get("sistema", "performance")).strip().lower()
    try:
        linhas = _servico_sheets().spreadsheets().values().get(
            spreadsheetId=segredo("TOKEN_SPREADSHEET_ID"), range=c.get("intervalo", "A1:C")).execute().get("values", [])
    except json.JSONDecodeError:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON inválido: confira se o conteúdo do creds.json foi colado inteiro, "
                           "com as chaves { } e todas as aspas.") from None
    except ImportError:
        raise RuntimeError("Instale google-api-python-client e google-auth (pip install -r requirements.txt).") from None
    except Exception as e:
        raise RuntimeError(f"Falha ao ler o token na planilha ({type(e).__name__}).") from None
    if not linhas:
        raise RuntimeError("A planilha de tokens está vazia ou sem acesso para a conta de serviço.")
    cab = [str(x).strip().lower() for x in linhas[0]]
    if not {"cliente", "sistema", "token"} <= set(cab):
        raise RuntimeError("A planilha de tokens precisa ter as colunas: cliente, sistema, token.")
    ic, isis, it = cab.index("cliente"), cab.index("sistema"), cab.index("token")
    for ln in linhas[1:]:
        ln = list(ln) + [""] * (len(cab) - len(ln))
        if str(ln[ic]).strip().lower() == tenant and str(ln[isis]).strip().lower() == sistema and str(ln[it]).strip():
            return _limpar(ln[it])
    raise RuntimeError(f"Token não encontrado na planilha para cliente '{tenant}' e sistema '{sistema}'.")


def invalidar_token():
    _cache.update(token=None, ate=0.0)


def token() -> str:
    if provedor_ativo():
        if _cache["token"] and time.time() < _cache["ate"]:
            return _cache["token"]
        try:
            t = _buscar_na_planilha()
            _info.update(origem="planilha", erro_planilha=None)
        except RuntimeError as e:
            _info["erro_planilha"] = str(e)
            fixo = _token_fixo()
            if fixo:
                _info["origem"] = "MINDSIGHT_TOKEN fixo (a planilha falhou)"
                return _limpar(fixo)
            raise
        _cache.update(token=t, ate=time.time() + 60 * int(_prov().get("ttl_min", 30)))
        return t
    t = _token_fixo()
    if t:
        _info["origem"] = "MINDSIGHT_TOKEN fixo"
        return _limpar(t)
    raise RuntimeError("Token ausente: configure a planilha de tokens (GOOGLE_CREDENTIALS_PATH e TOKEN_SPREADSHEET_ID) ou defina MINDSIGHT_TOKEN.")


def tem_token() -> bool:
    """Só confere a configuração (não faz chamada de rede)."""
    return provedor_ativo() or bool(_token_fixo())


def get(path: str, params: dict | None = None, tentativas: int = 5):
    c = cfg()
    url = path if path.startswith("http") else c["base_url"] + path.lstrip("/")
    ultimo = None
    renovou = False
    for i in range(tentativas):
        try:
            headers = {"Authorization": f"Token {token()}", "Accept": "application/json"}
            r = requests.get(url, headers=headers, params=params, timeout=c.get("timeout_s", 60))
            if r.status_code in (401, 403) and provedor_ativo() and not renovou:
                renovou = True  # token da planilha pode ter sido trocado/revogado: lê de novo uma vez
                invalidar_token()
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                ultimo = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(2 ** i)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            ultimo = e
            time.sleep(2 ** i)
    extra = f" [token vindo de: {_info['origem']}]"
    if _info["erro_planilha"]:
        extra += f" [erro ao ler a planilha: {_info['erro_planilha']}]"
    raise RuntimeError(f"Falha em {path}: {ultimo}{extra}")


def paginar(path: str, params: dict | None = None):
    """Gera os itens de `results`, seguindo `next` (page_size=200, nunca 100000)."""
    params = dict(params or {})
    params.setdefault("page_size", cfg().get("page_size", 200))
    data = get(path, params)
    while True:
        if isinstance(data, list):
            yield from data
            return
        yield from data.get("results", [])
        nxt = data.get("next")
        if not nxt:
            return
        data = get(nxt)  # `next` já traz todos os parâmetros
