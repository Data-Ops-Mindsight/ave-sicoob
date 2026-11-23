"""SQLite: schema, conexão e gravação atômica (snapshot)."""
from __future__ import annotations
import re
import sqlite3
from datetime import datetime
import pandas as pd
from config import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS pessoas(
  pessoa_id TEXT PRIMARY KEY, nome TEXT, email TEXT, cargo TEXT, area TEXT,
  macro_area TEXT, tags TEXT, is_gpc INTEGER DEFAULT 0,
  gestor_id TEXT, gestor_nome TEXT, avaliado INTEGER DEFAULT 0, atualizado_em TEXT);
CREATE TABLE IF NOT EXISTS respostas(
  pessoa_id TEXT, avaliador_id TEXT, marco INTEGER, papel TEXT, tipo TEXT,
  question_set INTEGER, competencia TEXT, pergunta TEXT, ordem INTEGER,
  nota REAL, resposta TEXT, comentario TEXT, texto TEXT, gestor_nome TEXT);
CREATE INDEX IF NOT EXISTS ix_resp ON respostas(pessoa_id, marco, papel);
CREATE TABLE IF NOT EXISTS pares(
  pessoa_id TEXT, avaliador_id TEXT, avaliador_nome TEXT, marco INTEGER,
  papel TEXT, pendente INTEGER);
CREATE INDEX IF NOT EXISTS ix_pares ON pares(pessoa_id, marco, papel);
CREATE TABLE IF NOT EXISTS catalogo(chave TEXT PRIMARY KEY, json TEXT, atualizado_em TEXT);
CREATE TABLE IF NOT EXISTS usuarios(
  usuario TEXT PRIMARY KEY, nome TEXT, hash_senha TEXT, perfil TEXT CHECK(perfil IN ('rh','bp')),
  pessoas_permitidas TEXT DEFAULT '[]', areas_permitidas TEXT DEFAULT '[]',
  cargos_permitidos TEXT DEFAULT '[]', pode_ver_texto INTEGER DEFAULT 0,
  pode_exportar INTEGER DEFAULT 0, expira_em TEXT, ativo INTEGER DEFAULT 1, criado_em TEXT, origem TEXT);
CREATE TABLE IF NOT EXISTS tentativas_login(usuario TEXT, ts TEXT, ok INTEGER);
CREATE TABLE IF NOT EXISTS log_acesso(ts TEXT, usuario TEXT, acao TEXT, detalhe TEXT);
CREATE TABLE IF NOT EXISTS coleta_log(ts TEXT, tipo TEXT, linhas INTEGER, ok INTEGER, erro TEXT);
CREATE TABLE IF NOT EXISTS meta(chave TEXT PRIMARY KEY, valor TEXT);
"""


try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("America/Sao_Paulo")
except Exception:
    _TZ = None


def agora_dt() -> datetime:
    """Agora, em horário de Brasília (naive). Use sempre este em vez de datetime.now()."""
    return datetime.now(_TZ).replace(tzinfo=None) if _TZ else datetime.now()


def agora() -> str:
    return agora_dt().isoformat(timespec="seconds")


def fmt_ts(ts) -> str:
    """'2026-11-22T14:05:00' -> '22/11/2026 às 14:05'. Vazio -> '—'."""
    try:
        return datetime.fromisoformat(ts).strftime("%d/%m/%Y às %H:%M")
    except (TypeError, ValueError):
        return "—"


def gravar_meta(chave, valor):
    con = conectar()
    with con:
        set_meta(con, chave, valor)
    con.close()


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(db_path(), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    _completar_colunas(con)
    return con


def _completar_colunas(con):
    """Bancos criados por versões antigas: acrescenta colunas que faltam (sem apagar dados)."""
    for tabela, ddl in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)\((.*?)\);", SCHEMA, flags=re.S):
        existentes = {r[1] for r in con.execute(f"PRAGMA table_info({tabela})")}
        for col in re.findall(r"(?:^|,)\s*(\w+)\s+(?:TEXT|INTEGER|REAL)", ddl):
            if col not in existentes:
                con.execute(f"ALTER TABLE {tabela} ADD COLUMN {col} TEXT")


def df(sql: str, params=()) -> pd.DataFrame:
    con = conectar()
    try:
        return pd.read_sql_query(sql, con, params=params)
    finally:
        con.close()


def set_meta(con, chave, valor):
    con.execute("INSERT INTO meta(chave,valor) VALUES(?,?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                (chave, str(valor)))


def get_meta(chave, default=None):
    con = conectar()
    try:
        r = con.execute("SELECT valor FROM meta WHERE chave=?", (chave,)).fetchone()
        return r["valor"] if r else default
    finally:
        con.close()


def log_coleta(tipo, linhas, ok=True, erro=None):
    con = conectar()
    with con:
        con.execute("INSERT INTO coleta_log VALUES(?,?,?,?,?)", (agora(), tipo, linhas, int(ok), erro))
    con.close()


def substituir_snapshot(con, tabela: str, linhas: list[dict], colunas: list[str]):
    """Troca o conteúdo da tabela numa única transação (atômico)."""
    ph = ",".join("?" * len(colunas))
    with con:
        con.execute(f"DELETE FROM {tabela}")
        con.executemany(f"INSERT INTO {tabela}({','.join(colunas)}) VALUES({ph})",
                        [tuple(r.get(c) for c in colunas) for r in linhas])
