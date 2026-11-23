"""Leitura do config.yaml e utilidades de caminho."""
from __future__ import annotations
import os
from functools import lru_cache
from pathlib import Path
import yaml

BASE = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def cfg() -> dict:
    with open(BASE / "config.yaml", encoding="utf-8") as f:
        c = yaml.safe_load(f)
    c["base_url"] = c["base_url"].format(tenant=c["tenant"])
    return c


def db_path() -> Path:
    p = Path(cfg()["db_path"])
    if not p.is_absolute():
        p = BASE / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def marco_final(m) -> int | None:
    """Aplica aliases (80 -> 90). Retorna None se não for numérico."""
    try:
        m = int(m)
    except (TypeError, ValueError):
        return None
    return int(cfg().get("marco_aliases", {}).get(m, m))


def resolver_marco_papel(question_set=None, group_key=None):
    """(marco, papel) a partir do config; nunca deduzido por texto."""
    c = cfg()
    qs = c.get("question_sets", {}) or {}
    if question_set is not None:
        try:
            r = qs.get(int(question_set))
        except (TypeError, ValueError):
            r = None
        if r:
            return marco_final(r["marco"]), r["papel"]
    r = (c.get("grupos", {}) or {}).get(group_key)
    if r:
        return marco_final(r["marco"]), r["papel"]
    return None, None


def pepper() -> bytes:
    """Segredo para pseudonimizar o CPF (`key`) em identificadores internos.
    Ordem: env AVE_PEPPER -> secrets.toml (AVE_PEPPER) -> data/.pepper (gerado 1x).
    Se mudar, os ids mudam (refaça a coleta e revise os escopos de BP por pessoa)."""
    v = os.environ.get("AVE_PEPPER")
    if not v:
        sp = BASE / ".streamlit" / "secrets.toml"
        if sp.exists():
            import tomllib
            with open(sp, "rb") as f:
                v = tomllib.load(f).get("AVE_PEPPER")
    if v:
        return v.encode()
    pf = db_path().parent / ".pepper"
    if not pf.exists():
        pf.write_text(os.urandom(32).hex())
        try:
            pf.chmod(0o600)
        except OSError:
            pass
    return pf.read_text().strip().encode()


@lru_cache(maxsize=1)
def _competencias() -> dict:
    p = BASE / "competencias.yaml"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("competencias", {})


def competencia(marco, papel, ordem, default=""):
    """Tema da pergunta (múltipla escolha) a partir de competencias.yaml; senão `default`."""
    try:
        return _competencias().get(f"{marco_final(marco)}_{papel}", {}).get(int(ordem)) or default
    except (TypeError, ValueError):
        return default


def _dotenv() -> dict:
    p = BASE / ".env"
    out = {}
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            if ln.startswith("export "):
                ln = ln[7:]
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


_erros: dict = {}


def erro_secrets() -> str | None:
    segredo("AVE_PEPPER")
    return _erros.get("secrets")


def segredo(nome: str) -> str | None:
    """Variável de ambiente, `.env` ou .streamlit/secrets.toml (nessa ordem)."""
    v = os.environ.get(nome) or _dotenv().get(nome)
    if v:
        return v.strip()
    sp = BASE / ".streamlit" / "secrets.toml"
    if sp.exists():
        import tomllib
        try:
            with open(sp, "rb") as f:
                v = tomllib.load(f).get(nome)
        except tomllib.TOMLDecodeError as e:
            _erros["secrets"] = f"secrets.toml com erro de sintaxe ({e}). Cada linha deve ser chave = \"valor\"."
            return None
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _simples(x):
    from collections.abc import Mapping
    if isinstance(x, Mapping):
        return {str(k): _simples(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_simples(v) for v in x]
    return x


def usuarios_secrets() -> list | None:
    """Tabelas `[[usuarios]]` dos secrets (arquivo local ou st.secrets). None se não houver a chave."""
    v = None
    sp = BASE / ".streamlit" / "secrets.toml"
    if sp.exists():
        import tomllib
        try:
            with open(sp, "rb") as f:
                v = tomllib.load(f).get("usuarios")
        except tomllib.TOMLDecodeError:
            return None
    if v is None:
        try:
            import streamlit as st
            v = st.secrets.get("usuarios")
        except Exception:
            v = None
    return _simples(v) if isinstance(v, (list, tuple)) else None


def caminho_arquivo(p: str) -> Path:
    """Caminho absoluto; relativo vale a partir da pasta atual ou, se não existir, da pasta do projeto."""
    c = Path(p).expanduser()
    return c if c.is_absolute() or c.exists() else BASE / c


@lru_cache(maxsize=1)
def descricoes_temas() -> dict:
    p = BASE / "competencias.yaml"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("temas", {})
