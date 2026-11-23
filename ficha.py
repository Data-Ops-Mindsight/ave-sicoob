"""Ficha por marco, status, comparativo e indicadores (sempre com escopo aplicado)."""
from __future__ import annotations
import json
import unicodedata
import pandas as pd
import db
import auth
from config import cfg

PAPEIS = ("gestor", "colaborador", "gpc")
ROTULO_PAPEL = {"gestor": "Gestor", "colaborador": "Autoavaliação", "gpc": "Parecer RH / GPC"}


def carregar() -> dict:
    return dict(pessoas=db.df("SELECT * FROM pessoas"), respostas=db.df("SELECT * FROM respostas"),
                pares=db.df("SELECT * FROM pares"),
                atualizacao=db.get_meta("ultima_coleta_respostas"))


def _norm(t) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(t)) if not unicodedata.combining(c)).strip().lower()


def tem_tag_experiencia(tags) -> bool:
    """True se a lista de tags do participante contém a tag configurada (sem diferenciar acento/caixa)."""
    if not isinstance(tags, str):
        return False
    try:
        lista = json.loads(tags)
    except ValueError:
        return False
    alvo = _norm(cfg().get("tag_em_experiencia", "Em experiência"))
    return any(_norm(t) == alvo for t in lista)


def pessoas_visiveis(dados: dict, u: dict) -> pd.DataFrame:
    """Colaboradores avaliados na rodada que têm a tag "Em experiência" (config), dentro do escopo do usuário."""
    av = dados["pessoas"][dados["pessoas"]["avaliado"] == 1].copy()
    if cfg().get("exigir_tag_experiencia", True):
        av = av[av["tags"].map(tem_tag_experiencia).astype(bool)]
    av["nome"] = av["nome"].fillna("(sem nome)")
    return auth.aplicar_escopo(av, u).sort_values("nome")


def status(dados, pid, marco, papel) -> str:
    """Só dois estados: Concluída (há respostas, ou o par já não está pendente) ou Pendente."""
    r, p = dados["respostas"], dados["pares"]
    if not r[(r.pessoa_id == pid) & (r.marco == marco) & (r.papel == papel)].empty:
        return "Concluída"
    pp = p[(p.pessoa_id == pid) & (p.marco == marco) & (p.papel == papel)]
    if not pp.empty and (pp.pendente == 0).all():
        return "Concluída"
    return "Pendente"


def _s(v):
    """NaN/None -> None; texto limpo."""
    if v is None or (isinstance(v, float) and v != v):
        return None
    v = str(v).strip()
    return v or None


def _bloco(dados, pid, marco, papel, ver_texto):
    r = dados["respostas"]
    r = r[(r.pessoa_id == pid) & (r.marco == marco) & (r.papel == papel)]
    esc = r[r.tipo == "escolha"].sort_values("ordem")
    ab = r[r.tipo == "aberta"].sort_values("ordem")
    notas = esc["nota"].dropna()
    return dict(
        papel=papel, status=status(dados, pid, marco, papel),
        media=float(notas.mean()) if len(notas) else None,
        itens=[dict(competencia=x.competencia, pergunta=x.pergunta, nota=_s(x.nota) and float(x.nota), resposta=_s(x.resposta),
                    comentario=_s(x.comentario) if ver_texto else None) for x in esc.itertuples()],
        abertas=[dict(pergunta=x.pergunta, texto=_s(x.texto)) for x in ab.itertuples() if _s(x.texto)] if ver_texto else [],
    )


def ficha(dados: dict, pid: str, u: dict, por_competencia: bool = True) -> dict | None:
    """Ficha completa; None se a pessoa está fora do escopo do usuário."""
    vis = pessoas_visiveis(dados, u)
    linha = vis[vis.pessoa_id == pid]
    if linha.empty:
        return None
    p = linha.iloc[0].to_dict()
    ver_texto = bool(u["perfil"] == "rh" or u.get("pode_ver_texto"))
    marcos = {}
    for m in cfg()["marcos"]:
        b = {papel: _bloco(dados, pid, m, papel, ver_texto) for papel in PAPEIS}
        if not ver_texto:  # GPC é restrito a quem pode ver texto
            b["gpc"] = dict(papel="gpc", status="Restrito", media=None, itens=[], abertas=[])
        marcos[m] = b
    return dict(pessoa=p, marcos=marcos, ver_texto=ver_texto, por_competencia=por_competencia,
                comparativo=comparativo(marcos, por_competencia))


def comparativo(marcos: dict, por_competencia: bool = True) -> pd.DataFrame:
    """Gestor x autoavaliação. Por competência (média dos temas) ou, se desligado, por pergunta
    (cada pergunta com a nota da sua visão; os formulários de gestor e colaborador têm perguntas diferentes)."""
    linhas = []
    if not por_competencia:
        for m, b in marcos.items():
            for papel in ("gestor", "colaborador"):
                for i in b[papel]["itens"]:
                    if i["nota"] is not None:
                        linhas.append(dict(marco=m, competencia=i["pergunta"],
                                           gestor=i["nota"] if papel == "gestor" else None,
                                           colaborador=i["nota"] if papel == "colaborador" else None))
        return pd.DataFrame(linhas, columns=["marco", "competencia", "gestor", "colaborador"])
    for m, b in marcos.items():
        def media(papel):  # média por competência (várias perguntas podem cair no mesmo tema)
            acc = {}
            for i in b[papel]["itens"]:
                if i["nota"] is not None:
                    acc.setdefault(i["competencia"], []).append(i["nota"])
            return {k: sum(v) / len(v) for k, v in acc.items()}
        g, c = media("gestor"), media("colaborador")
        for comp in dict.fromkeys(list(g) + list(c)):
            linhas.append(dict(marco=m, competencia=comp, gestor=g.get(comp), colaborador=c.get(comp)))
    return pd.DataFrame(linhas, columns=["marco", "competencia", "gestor", "colaborador"])


def andamento(dados: dict, vis: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por pessoa com o status de cada marco/papel."""
    linhas = []
    for p in vis.itertuples():
        row = dict(pessoa_id=p.pessoa_id, nome=p.nome, cargo=p.cargo, area=p.area, macro_area=p.macro_area,
                   gestor=p.gestor_nome)
        for m in cfg()["marcos"]:
            for papel in PAPEIS:
                row[f"{m}_{papel}"] = status(dados, p.pessoa_id, m, papel)
        linhas.append(row)
    return pd.DataFrame(linhas)


def indicadores(dados: dict, vis: pd.DataFrame, ver_texto: bool, por_competencia: bool = True) -> dict:
    ids = set(vis.pessoa_id)
    r = dados["respostas"]
    r = r[r.pessoa_id.isin(ids)]
    and_ = andamento(dados, vis)
    cont = []
    for m in cfg()["marcos"]:
        for papel in PAPEIS:
            if papel == "gpc" and not ver_texto:
                continue
            s = and_[f"{m}_{papel}"] if not and_.empty else pd.Series(dtype=str)
            cont.append(dict(marco=m, papel=papel, concluida=int((s == "Concluída").sum()),
                             pendente=int((s == "Pendente").sum())))
    esc = r[(r.tipo == "escolha") & r.nota.notna() & r.papel.isin(["gestor", "colaborador"])]
    col = "competencia" if por_competencia else "pergunta"  # por pergunta: a coluna segue chamada "competencia"
    medias = (esc.groupby(["marco", "papel", col])["nota"].mean().round(2).reset_index().rename(columns={col: "competencia"})
              if not esc.empty else pd.DataFrame(columns=["marco", "papel", "competencia", "nota"]))
    g = esc[esc.papel == "gestor"].groupby(["pessoa_id", "marco"])["nota"].mean().unstack()
    evol = dict(n=0, media_45=None, media_90=None, melhoraram=0)
    melhoraram = pd.DataFrame(columns=["nome", "cargo", "area", "gestor", "media_45", "media_90", "variacao"])
    if {45, 90} <= set(g.columns):
        gg = g.dropna(subset=[45, 90])
        evol = dict(n=len(gg), media_45=float(gg[45].mean()) if len(gg) else None,
                    media_90=float(gg[90].mean()) if len(gg) else None, melhoraram=int((gg[90] > gg[45]).sum()))
        m = gg[gg[90] > gg[45]].reset_index().rename(columns={45: "media_45", 90: "media_90"})
        m = m.merge(vis[["pessoa_id", "nome", "cargo", "area", "gestor_nome"]], on="pessoa_id", how="left")
        m["variacao"] = m["media_90"] - m["media_45"]
        melhoraram = (m.rename(columns={"gestor_nome": "gestor"})
                      [["nome", "cargo", "area", "gestor", "media_45", "media_90", "variacao"]]
                      .sort_values("variacao", ascending=False).reset_index(drop=True))
    decisoes = pd.DataFrame(columns=["marco", "decisao", "qtd"])
    if ver_texto and cfg().get("gpc_decisao_rotulo"):
        d = r[(r.papel == "gpc") & (r.tipo == "escolha") & (r.competencia == cfg()["gpc_decisao_rotulo"])]
        if not d.empty:
            decisoes = d.groupby(["marco", "resposta"]).size().reset_index(name="qtd").rename(columns={"resposta": "decisao"})
    return dict(total=len(vis), andamento=pd.DataFrame(cont), medias=medias, evolucao=evol, melhoraram=melhoraram,
                decisoes=decisoes,
                detalhe=and_)


def checar_pares_sem_resposta(dados: dict) -> pd.DataFrame:
    """RF4: pares concluídos (não pendentes) sem nenhuma resposta retornada pela API."""
    p, r = dados["pares"], dados["respostas"]
    p = p[p.pendente == 0]
    if p.empty:
        return p
    chaves = set(zip(r.pessoa_id, r.marco, r.papel))
    m = p[[(a, b, c) not in chaves for a, b, c in zip(p.pessoa_id, p.marco, p.papel)]]
    return m.merge(dados["pessoas"][["pessoa_id", "nome"]], on="pessoa_id", how="left")


def evolucao_competencias(f: dict) -> pd.DataFrame:
    """Média por competência, marco e visão (gestor/colaborador) de uma ficha."""
    linhas = []
    for m, b in f["marcos"].items():
        for papel in ("gestor", "colaborador"):
            acc = {}
            for i in b[papel]["itens"]:
                if i["nota"] is not None:
                    acc.setdefault(i["competencia"], []).append(i["nota"])
            linhas += [dict(marco=m, papel=papel, competencia=k, nota=sum(v) / len(v)) for k, v in acc.items()]
    return pd.DataFrame(linhas, columns=["marco", "papel", "competencia", "nota"])
