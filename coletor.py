"""Coletor: participantes + respostas + pares; catálogo. SEM atualização automática:
os dados só são buscados pelo botão da Tela inicial (mín. 5 min entre cliques) ou por estes comandos manuais.

Uso:
  python coletor.py --once                 # um ciclo completo (carga inicial / manutenção)
  python coletor.py --participantes|--respostas   # parcial
  python coletor.py --checar               # pares concluídos sem nenhuma resposta (valida o acesso admin da API)
  python coletor.py --catalogo             # catálogo 1x / sob demanda
  python coletor.py --grupos               # lista keys dos grupos (preencher config.yaml)
  python coletor.py --inspect              # 1ª página de cada endpoint (anonimizada) p/ ajustar models.py
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timedelta
import db
import api
import models
from config import cfg

RESP_COLS = ["pessoa_id", "avaliador_id", "marco", "papel", "tipo", "question_set", "competencia",
             "pergunta", "ordem", "nota", "resposta", "comentario", "texto", "gestor_nome"]
PAR_COLS = ["pessoa_id", "avaliador_id", "avaliador_nome", "marco", "papel", "pendente"]


def coletar_participantes() -> int:
    c = cfg()
    itens = list(api.paginar("participant_evaluation_round/", {
        "expand": "participant", "evaluation_round": c["rodada"]}))
    rows = models.norm_participantes(itens)
    con = db.conectar()
    with con:
        for r in rows:
            con.execute("""INSERT INTO pessoas(pessoa_id,nome,email,cargo,area,macro_area,tags,is_gpc,atualizado_em)
              VALUES(:pessoa_id,:nome,:email,:cargo,:area,:macro_area,:tags,:is_gpc,:ts)
              ON CONFLICT(pessoa_id) DO UPDATE SET nome=excluded.nome,email=excluded.email,
              cargo=excluded.cargo,area=excluded.area,macro_area=excluded.macro_area,
              tags=excluded.tags,is_gpc=excluded.is_gpc,atualizado_em=excluded.atualizado_em""",
                        {**r, "ts": db.agora()})
        db.set_meta(con, "ultima_coleta_participantes", db.agora())
    con.close()
    return len(rows)


def coletar_respostas() -> int:
    c = cfg()
    rid = c["rodada"]
    f = {"evaluation__evaluation_group__evaluation_round__id": rid, "view_as": "admin"}
    escolha = models.norm_choice(list(api.paginar("choice_answers/grades/", f)))
    abertas = models.norm_open(list(api.paginar("open_answers/grades/", f)))
    pares = models.norm_pares(list(api.paginar(f"evaluation_rounds/{rid}/admin_evaluation_pairs/")))
    respostas = escolha + abertas
    aplicar_snapshot(respostas, pares)
    return len(respostas) + len(pares)


def aplicar_snapshot(respostas: list[dict], pares: list[dict]):
    """Grava respostas/pares de forma atômica e atualiza avaliado/gestor em `pessoas`."""
    con = db.conectar()
    with con:
        con.execute("DELETE FROM respostas")
        con.executemany(f"INSERT INTO respostas({','.join(RESP_COLS)}) VALUES({','.join('?'*len(RESP_COLS))})",
                        [tuple(r.get(k) for k in RESP_COLS) for r in respostas])
        con.execute("DELETE FROM pares")
        con.executemany(f"INSERT INTO pares({','.join(PAR_COLS)}) VALUES({','.join('?'*len(PAR_COLS))})",
                        [tuple(r.get(k) for k in PAR_COLS) for r in pares])
        # garante linha em pessoas (avaliados e avaliadores) com nome; cargo/área só se faltarem
        for r in respostas + pares:
            con.execute("INSERT OR IGNORE INTO pessoas(pessoa_id,nome) VALUES(?,?)",
                        (r["pessoa_id"], r.get("_nome_avaliado")))
            con.execute("UPDATE pessoas SET nome=? WHERE pessoa_id=? AND (nome IS NULL OR nome='')",
                        (r.get("_nome_avaliado"), r["pessoa_id"]))
            if r.get("_cargo") or r.get("_area"):
                con.execute("""UPDATE pessoas SET cargo=CASE WHEN COALESCE(cargo,'')='' THEN ? ELSE cargo END,
                               area=CASE WHEN COALESCE(area,'')='' THEN ? ELSE area END,
                               macro_area=CASE WHEN COALESCE(area,'')='' THEN ? ELSE macro_area END
                               WHERE pessoa_id=?""",
                            (r.get("_cargo"), r.get("_area"), models.macro_area(r.get("_area")), r["pessoa_id"]))
        for p in pares:
            if p.get("avaliador_id"):
                con.execute("INSERT OR IGNORE INTO pessoas(pessoa_id,nome) VALUES(?,?)",
                            (p["avaliador_id"], p.get("avaliador_nome")))
        con.execute("UPDATE pessoas SET avaliado=0")
        ids = {p["pessoa_id"] for p in pares} | {r["pessoa_id"] for r in respostas}
        con.executemany("UPDATE pessoas SET avaliado=1 WHERE pessoa_id=?", [(i,) for i in ids])
        # gestor: pares (papel gestor) e, na falta, o campo `manager` das respostas
        con.execute("UPDATE pessoas SET gestor_id=NULL, gestor_nome=NULL")
        for p in pares:
            if p.get("papel") == "gestor" and p.get("avaliador_id"):
                con.execute("""UPDATE pessoas SET gestor_id=?, gestor_nome=COALESCE(?,
                    (SELECT nome FROM pessoas WHERE pessoa_id=?)) WHERE pessoa_id=?""",
                            (p["avaliador_id"], p.get("avaliador_nome"), p["avaliador_id"], p["pessoa_id"]))
        for r in respostas:
            if r.get("gestor_nome"):
                con.execute("UPDATE pessoas SET gestor_nome=? WHERE pessoa_id=? AND gestor_nome IS NULL",
                            (r["gestor_nome"], r["pessoa_id"]))
        db.set_meta(con, "ultima_coleta_respostas", db.agora())
    con.close()


def coletar_catalogo() -> int:
    c = cfg()
    rid = c["rodada"]
    base = {"evaluation_round": rid, "in_eval_round": rid, "page_size": 5000}
    con = db.conectar()
    total = 0
    for chave in ["evaluation_groups", "question_modules", "question_set_in_round",
                  "choice_question_in_round", "open_question_in_round"]:
        itens = list(api.paginar(f"{chave}/", base))
        total += len(itens)
        with con:
            con.execute("INSERT INTO catalogo VALUES(?,?,?) ON CONFLICT(chave) DO UPDATE SET json=excluded.json,"
                        "atualizado_em=excluded.atualizado_em", (chave, json.dumps(itens, ensure_ascii=False), db.agora()))
    con.close()
    return total


def ciclo(participantes=True, respostas=True, catalogo=False):
    res = []
    for nome, flag, fn in (("participantes", participantes, coletar_participantes),
                           ("respostas", respostas, coletar_respostas),
                           ("catalogo", catalogo, coletar_catalogo)):
        if not flag:
            continue
        try:
            n = fn()
            db.log_coleta(nome, n)
            print(f"[{db.agora()}] {nome}: {n} linhas")
            res.append((nome, True, ""))
        except Exception as e:  # painel segue no ar com o último snapshot
            db.log_coleta(nome, 0, False, str(e)[:500])
            print(f"[{db.agora()}] {nome}: ERRO {e}")
            res.append((nome, False, str(e)[:200]))
    return res


def espera_s() -> int:
    return int(cfg().get("espera_atualizacao_min", 5)) * 60


def espera_restante() -> int:
    """Segundos até a próxima atualização ser liberada (0 = liberada)."""
    ult = db.get_meta("ultima_atualizacao_manual")
    if not ult:
        return 0
    try:
        falta = espera_s() - (db.agora_dt() - datetime.fromisoformat(ult)).total_seconds()
    except ValueError:
        return 0
    return int(falta) + 1 if falta > 0 else 0


def liberado_em():
    """datetime em que a próxima atualização é liberada (None se já está liberada)."""
    ult = db.get_meta("ultima_atualizacao_manual")
    try:
        t = datetime.fromisoformat(ult) + timedelta(seconds=espera_s())
    except (TypeError, ValueError):
        return None
    return t if t > db.agora_dt() else None


def fmt_espera(seg: int) -> str:
    return f"{seg // 60} min {seg % 60:02d} s"


def atualizar_manual() -> tuple[bool, str]:
    """Atualização disparada pelo botão da Tela inicial (participantes + respostas + pares).
    Limite global: uma atualização a cada `espera_atualizacao_min` minutos, para qualquer usuário."""
    falta = espera_restante()
    if falta > 0:
        return False, f"Os dados foram atualizados há pouco. Nova atualização liberada em {fmt_espera(falta)}."
    db.gravar_meta("ultima_atualizacao_manual", db.agora())  # marca antes: bloqueia cliques simultâneos
    res = ciclo()
    erros = [f"{n}: {m}" for n, ok, m in res if not ok]
    if erros:  # falha: libera nova tentativa em 1 min (em vez de esperar o intervalo todo)
        db.gravar_meta("ultima_atualizacao_manual",
                       (db.agora_dt() - timedelta(seconds=max(espera_s() - 60, 0))).isoformat(timespec="seconds"))
        return False, "Falha na atualização (o painel continua com os últimos dados). " + " | ".join(erros)
    return True, "Dados atualizados."


def inspecionar():
    rid = cfg()["rodada"]
    eps = {"participantes": ("participant_evaluation_round/", {"expand": "participant", "evaluation_round": rid, "page_size": 2}),
           "choice_answers": ("choice_answers/grades/", {"evaluation__evaluation_group__evaluation_round__id": rid, "view_as": "admin", "page_size": 2}),
           "open_answers": ("open_answers/grades/", {"evaluation__evaluation_group__evaluation_round__id": rid, "view_as": "admin", "page_size": 2}),
           "pares": (f"evaluation_rounds/{rid}/admin_evaluation_pairs/", {"page_size": 2})}
    sens = {"key", "email", "username", "name", "cpf", "manager", "photo"}

    def anon(o, k=""):
        if isinstance(o, dict):
            return {kk: anon(v, kk) for kk, v in o.items()}
        if isinstance(o, list):
            return [anon(x, k) for x in o]
        if k in sens or k.endswith(("_key", "_name")) and k != "evaluation_group_name":
            return "***"
        return o
    for nome, (p, params) in eps.items():
        d = api.get(p, params)
        print(f"\n=== {nome} ===")
        a = anon(d)
        if nome == "open_answers":  # texto livre também é sensível
            for r_ in a.get("results", []):
                r_["answer"] = "***"
        print(json.dumps(a, ensure_ascii=False, indent=1)[:3500])


def listar_grupos():
    rid = cfg()["rodada"]
    for g_ in api.paginar("evaluation_groups/", {"evaluation_round": rid, "page_size": 500}):
        print(repr(g_.get("key")), "| id:", g_.get("id"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for a in ("once", "participantes", "respostas", "catalogo", "grupos", "inspect", "checar"):
        ap.add_argument(f"--{a}", action="store_true")
    a = ap.parse_args()
    if a.checar:
        import ficha
        r = ficha.checar_pares_sem_resposta(ficha.carregar())
        print("Nenhuma inconsistência." if r.empty else f"{len(r)} pares concluídos sem resposta retornada pela API:\n"
              + r[["nome", "marco", "papel"]].to_string(index=False))
        return
    if a.grupos:
        return listar_grupos()
    if a.inspect:
        return inspecionar()
    if a.catalogo:
        return ciclo(False, False, True)
    if a.participantes or a.respostas:
        return ciclo(a.participantes, a.respostas)
    if a.once:
        return ciclo()
    ap.print_help()


if __name__ == "__main__":
    main()
