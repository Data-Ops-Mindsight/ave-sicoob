"""Autenticação, perfis (rh|bp), escopo no servidor e auditoria.

CLI:  python auth.py criar-rh usuario "Nome"   |   python auth.py gerar-hash   |   python auth.py listar
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
import sys
from datetime import date, datetime, time as dtime, timedelta
import pandas as pd
import db
from config import cfg, usuarios_secrets

try:
    import bcrypt
except ImportError:  # fallback pbkdf2 (instale bcrypt em produção)
    bcrypt = None


def hash_senha(s: str) -> str:
    if bcrypt:
        return "bcrypt$" + bcrypt.hashpw(s.encode(), bcrypt.gensalt()).decode()
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", s.encode(), salt, 310_000)
    return "pbkdf2$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def verificar_senha(s: str, h: str) -> bool:
    try:
        if h.startswith("bcrypt$") and bcrypt:
            return bcrypt.checkpw(s.encode(), h[7:].encode())
        if h.startswith("pbkdf2$"):
            _, salt, dig = h.split("$")
            novo = hashlib.pbkdf2_hmac("sha256", s.encode(), base64.b64decode(salt), 310_000)
            return hmac.compare_digest(novo, base64.b64decode(dig))
    except Exception:
        pass
    return False


def _j(v):
    return json.loads(v) if v else []


def criar_usuario(usuario, nome, senha, perfil, pessoas=None, areas=None, cargos=None,
                  pode_ver_texto=False, pode_exportar=False, expira_em=None):
    assert perfil in ("rh", "bp")
    con = db.conectar()
    with con:
        con.execute("""INSERT INTO usuarios(usuario,nome,hash_senha,perfil,pessoas_permitidas,areas_permitidas,
                       cargos_permitidos,pode_ver_texto,pode_exportar,expira_em,ativo,criado_em)
                       VALUES(?,?,?,?,?,?,?,?,?,?,1,?)""",
                    (usuario, nome, hash_senha(senha), perfil, json.dumps(pessoas or []), json.dumps(areas or []),
                     json.dumps(cargos or []), int(pode_ver_texto or perfil == "rh"),
                     int(pode_exportar or perfil == "rh"), expira_em, db.agora()))
    con.close()


def atualizar_bp(usuario, nome, pessoas, areas, cargos, pode_ver_texto, pode_exportar, expira_em, ativo, nova_senha=None):
    con = db.conectar()
    with con:
        con.execute("""UPDATE usuarios SET nome=?,pessoas_permitidas=?,areas_permitidas=?,cargos_permitidos=?,
                       pode_ver_texto=?,pode_exportar=?,expira_em=?,ativo=? WHERE usuario=? AND perfil='bp'
                       AND COALESCE(origem,'')<>'secrets'""",
                    (nome, json.dumps(pessoas), json.dumps(areas), json.dumps(cargos), int(pode_ver_texto),
                     int(pode_exportar), expira_em, int(ativo), usuario))
        if nova_senha:
            con.execute("UPDATE usuarios SET hash_senha=? WHERE usuario=? AND COALESCE(origem,'')<>'secrets'",
                        (hash_senha(nova_senha), usuario))
    con.close()


def remover_usuario(usuario):
    con = db.conectar()
    with con:
        con.execute("DELETE FROM usuarios WHERE usuario=? AND COALESCE(origem,'')<>'secrets'", (usuario,))
    con.close()


def listar_usuarios() -> pd.DataFrame:
    return db.df("SELECT usuario,nome,perfil,pessoas_permitidas,areas_permitidas,cargos_permitidos,"
                 "pode_ver_texto,pode_exportar,expira_em,ativo,criado_em,origem FROM usuarios ORDER BY perfil,usuario")


def obter_usuario(usuario) -> dict | None:
    con = db.conectar()
    r = con.execute("SELECT * FROM usuarios WHERE usuario=?", (usuario,)).fetchone()
    con.close()
    if not r:
        return None
    d = dict(r)
    for k in ("pessoas_permitidas", "areas_permitidas", "cargos_permitidos"):
        d[k] = _j(d[k])
    return d


_sig = {"v": None}


def _lista(v) -> list:
    if isinstance(v, str):
        v = [v]
    return [str(i) for i in v] if isinstance(v, (list, tuple)) else []


def _expira(v):
    if isinstance(v, datetime):
        return v.isoformat(timespec="seconds")
    if isinstance(v, date):
        return datetime.combine(v, dtime(23, 59)).isoformat(timespec="seconds")
    v = str(v).strip() if v else None
    return v + "T23:59:00" if v and len(v) == 10 else v


def sincronizar_secrets():
    """Usuários declarados em `[[usuarios]]` nos secrets viram a fonte oficial: são criados/atualizados no
    banco e os que saírem da lista são removidos. Só roda de novo se o conteúdo dos secrets mudar."""
    lista = usuarios_secrets()
    if lista is None:
        return
    sig = hashlib.sha256(json.dumps(lista, sort_keys=True, default=str).encode()).hexdigest()
    if _sig["v"] == sig:
        return
    ok, invalidos = [], []
    con = db.conectar()
    with con:
        for x in lista:
            u = str(x.get("usuario", "")).strip().lower()
            perfil, h = x.get("perfil"), str(x.get("hash_senha", ""))
            if not u or perfil not in ("rh", "bp") or not h.startswith(("bcrypt$", "pbkdf2$")):
                invalidos.append(u or "?")
                continue
            rh_ = perfil == "rh"
            v = (u, str(x.get("nome") or u), h, perfil, json.dumps(_lista(x.get("pessoas_permitidas"))),
                 json.dumps(_lista(x.get("areas_permitidas"))), json.dumps(_lista(x.get("cargos_permitidos"))),
                 int(rh_ or bool(x.get("pode_ver_texto"))), int(rh_ or bool(x.get("pode_exportar"))),
                 _expira(x.get("expira_em")), int(bool(x.get("ativo", True))), db.agora())
            con.execute("""INSERT INTO usuarios(usuario,nome,hash_senha,perfil,pessoas_permitidas,areas_permitidas,
                           cargos_permitidos,pode_ver_texto,pode_exportar,expira_em,ativo,criado_em,origem)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'secrets')
                           ON CONFLICT(usuario) DO UPDATE SET nome=excluded.nome, hash_senha=excluded.hash_senha,
                           perfil=excluded.perfil, pessoas_permitidas=excluded.pessoas_permitidas,
                           areas_permitidas=excluded.areas_permitidas, cargos_permitidos=excluded.cargos_permitidos,
                           pode_ver_texto=excluded.pode_ver_texto, pode_exportar=excluded.pode_exportar,
                           expira_em=excluded.expira_em, ativo=excluded.ativo, origem='secrets'""", v)
            ok.append(u)
        marcas = ",".join("?" * len(ok))
        con.execute(f"DELETE FROM usuarios WHERE origem='secrets'" + (f" AND usuario NOT IN ({marcas})" if ok else ""), ok)
    con.close()
    _sig["v"] = sig
    registrar("(servidor)", "sincronizar_usuarios_secrets", f"{len(ok)} ok" + (f"; inválidos: {', '.join(invalidos)}" if invalidos else ""))


def existe_rh() -> bool:
    return not db.df("SELECT 1 FROM usuarios WHERE perfil='rh' AND ativo=1 LIMIT 1").empty


def _bloqueado(con, usuario) -> bool:
    c = cfg()
    desde = (db.agora_dt() - timedelta(minutes=c["login_janela_min"])).isoformat(timespec="seconds")
    n = con.execute("SELECT COUNT(*) FROM tentativas_login WHERE usuario=? AND ok=0 AND ts>=?",
                    (usuario, desde)).fetchone()[0]
    return n >= c["login_max_falhas"]


def expirado(u: dict) -> bool:
    if not u.get("expira_em"):
        return False
    try:
        return datetime.fromisoformat(u["expira_em"]) < db.agora_dt()
    except ValueError:
        return True


def login(usuario: str, senha: str) -> tuple[dict | None, str]:
    """(usuario, mensagem). Bloqueia após N falhas na janela."""
    usuario = (usuario or "").strip().lower()
    con = db.conectar()
    try:
        if _bloqueado(con, usuario):
            registrar(usuario, "login_bloqueado", "")
            return None, "Muitas tentativas. Tente novamente em alguns minutos."
        u = obter_usuario(usuario)
        ok = bool(u and u["ativo"] and verificar_senha(senha, u["hash_senha"]) and not expirado(u))
        with con:
            con.execute("INSERT INTO tentativas_login VALUES(?,?,?)", (usuario, db.agora(), int(ok)))
        if not ok:
            registrar(usuario, "login_falha", "")
            return None, "Usuário ou senha inválidos, ou acesso expirado/revogado."
        registrar(usuario, "login", "")
        u.pop("hash_senha", None)
        return u, ""
    finally:
        con.close()


def registrar(usuario, acao, detalhe=""):
    con = db.conectar()
    with con:
        con.execute("INSERT INTO log_acesso VALUES(?,?,?,?)", (db.agora(), usuario, acao, detalhe))
    con.close()


# ---------- escopo (aplicado ao montar o dataframe, antes de tela/PDF) ----------
def aplicar_escopo(pessoas: pd.DataFrame, u: dict) -> pd.DataFrame:
    if u["perfil"] == "rh":
        return pessoas
    if expirado(u) or not u.get("ativo", 1):
        return pessoas.iloc[0:0]
    crit = []
    if u["pessoas_permitidas"]:
        crit.append(pessoas["pessoa_id"].isin(u["pessoas_permitidas"]))
    if u["areas_permitidas"]:
        # aceita área completa ou macro-área
        crit.append(pessoas["area"].isin(u["areas_permitidas"]) | pessoas["macro_area"].isin(u["areas_permitidas"]))
    if u["cargos_permitidos"]:
        crit.append(pessoas["cargo"].isin(u["cargos_permitidos"]))
    if not crit:  # sem critério definido = sem acesso
        return pessoas.iloc[0:0]
    m = crit[0]
    for c_ in crit[1:]:
        m = (m | c_) if cfg().get("bp_escopo_modo", "uniao") == "uniao" else (m & c_)
    return pessoas[m]


def main():
    import getpass
    a = sys.argv[1:]
    if a[:1] == ["criar-rh"] and len(a) >= 3:
        s = getpass.getpass("Senha: ")
        criar_usuario(a[1].lower(), a[2], s, "rh")
        registrar("(servidor)", "criar_rh", a[1].lower())
        print("RH criado.")
    elif a[:1] == ["gerar-hash"]:
        print(hash_senha(getpass.getpass("Senha: ")))
    elif a[:1] == ["listar"]:
        print(listar_usuarios().to_string())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
