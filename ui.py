"""Helpers Streamlit: tema Sicoob, login/sessão, filtros, gráficos."""
from __future__ import annotations
import html
import time
import pandas as pd
import streamlit as st
import auth
import db
import brand as B
import ficha
from config import cfg, erro_secrets

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Asap:wght@400;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, button, input, textarea {{ font-family: {B.FONTE_CSS} !important; }}
h1, h2, h3 {{ color: {B.VERDE_ESCURO}; font-weight: 700; }}
h1 {{ border-bottom: 4px solid {B.TURQUESA}; padding-bottom: .3rem; }}
[data-testid="stSidebar"] {{ background: {B.FUNDO_SUAVE}; }}
[data-testid="stMetric"] {{ background: {B.FUNDO_SUAVE}; border-left: 5px solid {B.TURQUESA};
  padding: .6rem .9rem; border-radius: 6px; }}
[data-testid="stMetricValue"] {{ color: {B.VERDE_ESCURO}; }}
.stButton>button[kind="primary"], .stDownloadButton>button {{ background: {B.TURQUESA}; color: #fff; border: 0; }}
.bloco {{ border-top: 4px solid var(--c); background: {B.FUNDO_SUAVE}; padding: .6rem .8rem; border-radius: 6px; }}
.comp {{ border:1px solid #D5E3E0; border-radius:8px; margin:0 0 .9rem 0; overflow:hidden; }}
.comp-h {{ display:flex; justify-content:space-between; background:{B.VERDE_ESCURO}; color:#fff; padding:.45rem .8rem; font-weight:700; }}
.comp-m {{ color:{B.VERDE_CLARO}; font-weight:600; }}
.q {{ display:flex; justify-content:space-between; gap:1rem; align-items:center; padding:.5rem .8rem; border-top:1px solid #E6EFED; }}
.q:first-of-type {{ border-top:0; }}
.q-t {{ color:{B.VERDE_ESCURO}; line-height:1.35; }}
.pill {{ white-space:nowrap; padding:3px 12px; border-radius:14px; font-size:.82rem; font-weight:700; }}
.just {{ margin:0 .8rem .6rem .8rem; padding:.45rem .7rem; border-left:4px solid {B.TURQUESA}; background:{B.FUNDO_SUAVE};
  color:{B.VERDE_ESCURO}; font-size:.92rem; line-height:1.45; }}
.aberta {{ border-left:5px solid {B.ROXO}; background:{B.FUNDO_SUAVE}; border-radius:0 8px 8px 0; padding:.7rem 1rem; margin:0 0 .9rem 0; }}
.aberta-p {{ font-weight:700; color:{B.VERDE_ESCURO}; margin-bottom:.3rem; }}
.aberta-t {{ color:{B.VERDE_ESCURO}; line-height:1.55; }}
.chip {{ display:inline-block; padding:2px 10px; border-radius:12px; color:#fff; font-size:.8rem; font-weight:600; }}
</style>
"""


def chip(status: str) -> str:
    cor = B.STATUS_COR.get(status, "#9AA8AB")
    txt = "#fff" if cor == B.ROXO else B.VERDE_ESCURO
    return f'<span class="chip" style="background:{cor};color:{txt}">{status}</span>'


def _login_form():
    st.markdown("# AVE – Avaliação de Experiência")
    st.caption(f"Sicoob Cocred · {cfg()['rodada_nome']}")
    if not auth.existe_rh():
        st.warning("Nenhum usuário RH cadastrado. No servidor, rode: `python auth.py criar-rh <usuario> \"Nome\"`.")
    with st.form("login"):
        u = st.text_input("Usuário")
        s = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            user, msg = auth.login(u, s)
            if user:
                st.session_state["user"] = user
                st.session_state["ultimo_uso"] = time.time()
                st.rerun()
            else:
                st.error(msg)


def boot() -> dict:
    """Chamado UMA vez no app.py: tema, login, expiração de sessão e revalidação. Devolve o usuário."""
    st.set_page_config(page_title="AVE · Sicoob Cocred", page_icon="✅", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    auth.sincronizar_secrets()
    user = st.session_state.get("user")
    exp = cfg()["sessao_expira_min"] * 60
    if user and time.time() - st.session_state.get("ultimo_uso", 0) > exp:
        auth.registrar(user["usuario"], "sessao_expirada")
        st.session_state.pop("user", None)
        user = None
        st.info("Sessão expirada. Entre novamente.")
    if user:  # revalida a cada interação (revogação/expiração valem na hora)
        atual = auth.obter_usuario(user["usuario"])
        if not atual or not atual["ativo"] or auth.expirado(atual):
            st.session_state.pop("user", None)
            user = None
        else:
            atual.pop("hash_senha", None)
            user = st.session_state["user"] = atual
    if not user:
        _login_form()
        st.stop()
    st.session_state["ultimo_uso"] = time.time()
    with st.sidebar:
        st.markdown(f"**{user['nome']}**  \nPerfil: `{user['perfil'].upper()}`")
        if user.get("expira_em"):
            st.caption(f"Acesso até {user['expira_em'][:10]}")
        if st.button("Sair"):
            auth.registrar(user["usuario"], "logout")
            st.session_state.clear()
            st.rerun()
    return user


def pagina(titulo: str, so_rh: bool = False) -> dict:
    """Início de cada página: confere o perfil e mostra o título. Devolve o usuário logado."""
    user = st.session_state.get("user")
    if not user:
        st.stop()
    if so_rh and user["perfil"] != "rh":
        st.error("Acesso restrito ao perfil RH.")
        st.stop()
    st.title(titulo)
    return user


@st.cache_data(ttl=60, show_spinner=False)
def dados() -> dict:
    return ficha.carregar()


def rodape_atualizacao(d=None):
    st.sidebar.caption(f"Dados atualizados em {db.fmt_ts(db.get_meta('ultima_coleta_respostas'))}")


def filtros(vis: pd.DataFrame, chave="f") -> tuple[pd.DataFrame, str]:
    """Filtros de macro-área, área, cargo e gestor. Devolve (df, descrição)."""
    desc = []
    with st.sidebar:
        st.markdown("### Filtros")
        for col, rot in (("macro_area", "Macro-área"), ("area", "Área"), ("cargo", "Cargo"), ("gestor_nome", "Gestor")):
            opts = sorted(x for x in vis[col].dropna().unique() if x)
            sel = st.multiselect(rot, opts, key=f"{chave}_{col}")
            if sel:
                vis = vis[vis[col].isin(sel)]
                desc.append(f"{rot}: {', '.join(sel)}")
    return vis, " | ".join(desc)


def aviso_tag():
    st.caption(f"Aparecem aqui apenas colaboradores com a tag “{cfg().get('tag_em_experiencia', 'Em experiência')}” na rodada.")


def barras_comparativo(comp: pd.DataFrame, por_pergunta: bool = False):
    """Gestor x autoavaliação por competência (altair, paleta Sicoob, com rótulos)."""
    import altair as alt
    if comp.empty:
        return None
    long = comp.melt(id_vars=["marco", "competencia"], value_vars=["gestor", "colaborador"],
                     var_name="visao", value_name="nota").dropna()
    long["visao"] = long["visao"].map({"gestor": "Gestor", "colaborador": "Autoavaliação"})
    enc = dict(
        y=alt.Y("competencia:N", title=None, sort=None, axis=alt.Axis(labelLimit=560 if por_pergunta else 220)),
        x=alt.X("nota:Q", scale=alt.Scale(domain=[0, cfg()["escala_max"]]), title="Nota"),
        color=alt.Color("visao:N", scale=alt.Scale(domain=["Gestor", "Autoavaliação"],
                                                    range=[B.VERDE_ESCURO, B.TURQUESA]), legend=alt.Legend(title=None, orient="top")))
    if not por_pergunta:  # por pergunta cada linha tem uma só barra (as perguntas de gestor e colaborador diferem)
        enc["yOffset"] = "visao:N"
    base = alt.Chart(long).encode(**enc)
    linha = 28 if por_pergunta else 38
    return (base.mark_bar() + base.mark_text(align="left", dx=3, color=B.VERDE_ESCURO).encode(
        text=alt.Text("nota:Q", format=".1f"))).properties(height=max(160, linha * long["competencia"].nunique()))


def barras_status(and_df: pd.DataFrame):
    import altair as alt
    if and_df.empty:
        return None
    long = and_df.melt(id_vars=["marco", "papel"], value_vars=["concluida", "pendente"],
                       var_name="status", value_name="qtd")
    nomes = {"concluida": "Concluída", "pendente": "Pendente"}
    long["status"] = long["status"].map(nomes)
    long["visao"] = long["marco"].astype(str) + "d · " + long["papel"].map(ficha.ROTULO_PAPEL)
    return alt.Chart(long).mark_bar().encode(
        y=alt.Y("visao:N", title=None, sort=None), x=alt.X("qtd:Q", title="Colaboradores"),
        color=alt.Color("status:N", scale=alt.Scale(domain=list(nomes.values()),
                        range=[B.VERDE_MEDIO, B.ROXO]), legend=alt.Legend(title=None, orient="top")),
        tooltip=["visao", "status", "qtd"]).properties(height=280)


# ---------- respostas legíveis (todo texto de usuário passa por html.escape) ----------
def _h(t) -> str:
    return html.escape(str(t)).replace("\n", "<br>")


def _pill(nota, resposta) -> str:
    if nota is None:
        return ""
    fundo, texto = B.NOTA_COR.get(int(round(nota)), (B.VERDE_ESCURO, "#fff"))
    return f'<span class="pill" style="background:{fundo};color:{texto}">{nota:.0f} · {_h(resposta or "")}</span>'


def html_escolha(itens) -> str:
    """Perguntas de múltipla escolha agrupadas por competência, com nota em destaque e justificativa."""
    grupos: dict = {}
    for i in itens:
        grupos.setdefault(i["competencia"], []).append(i)
    out = []
    for comp, its in grupos.items():
        notas = [i["nota"] for i in its if i["nota"] is not None]
        media = f"média {sum(notas) / len(notas):.1f}".replace(".", ",") if notas else ""
        out.append(f'<div class="comp"><div class="comp-h"><span>{_h(comp)}</span><span class="comp-m">{media}</span></div>')
        for i in its:
            out.append(f'<div class="q"><div class="q-t">{_h(i["pergunta"])}</div>{_pill(i["nota"], i["resposta"])}</div>')
            if i["comentario"]:
                out.append(f'<div class="just"><b>Justificativa:</b> {_h(i["comentario"])}</div>')
        out.append("</div>")
    return "".join(out)


def html_abertas(abertas) -> str:
    return "".join(f'<div class="aberta"><div class="aberta-p">{_h(a["pergunta"])}</div>'
                   f'<div class="aberta-t">{_h(a["texto"])}</div></div>' for a in abertas)


def barras_evolucao(df: pd.DataFrame):
    """Competência x marco (45 vs 90) para uma visão (df já filtrado por papel)."""
    import altair as alt
    if df.empty or df["marco"].nunique() < 2:
        return None
    df = df.assign(marco=df["marco"].astype(str) + " dias")
    base = alt.Chart(df).encode(
        y=alt.Y("competencia:N", title=None, sort=None), yOffset="marco:N",
        x=alt.X("nota:Q", scale=alt.Scale(domain=[0, cfg()["escala_max"]]), title="Nota média"),
        color=alt.Color("marco:N", scale=alt.Scale(domain=["45 dias", "90 dias"], range=[B.TURQUESA, B.VERDE_ESCURO]),
                        legend=alt.Legend(title=None, orient="top")))
    return (base.mark_bar() + base.mark_text(align="left", dx=3, color=B.VERDE_ESCURO).encode(
        text=alt.Text("nota:Q", format=".1f"))).properties(height=max(180, 44 * df["competencia"].nunique()))


def halteres_melhora(df: pd.DataFrame):
    """Quem melhorou: ponto 45d -> ponto 90d por colaborador."""
    import altair as alt
    if df.empty:
        return None
    ordem = list(df.sort_values("variacao", ascending=False)["nome"])
    x = alt.X("nota:Q", scale=alt.Scale(domain=[1, cfg()["escala_max"]]), title="Nota média do gestor")
    y = alt.Y("nome:N", sort=ordem, title=None)
    linha = alt.Chart(df).mark_rule(color=B.TURQUESA, strokeWidth=3).encode(
        y=y, x=alt.X("media_45:Q", scale=alt.Scale(domain=[1, cfg()["escala_max"]])), x2="media_90:Q")
    long = df.melt(id_vars=["nome"], value_vars=["media_45", "media_90"], var_name="marco", value_name="nota")
    long["marco"] = long["marco"].map({"media_45": "45 dias", "media_90": "90 dias"})
    pontos = alt.Chart(long).mark_point(filled=True, size=110, opacity=1).encode(
        y=y, x=x, color=alt.Color("marco:N", scale=alt.Scale(domain=["45 dias", "90 dias"],
                                  range=[B.VERDE_ESCURO, B.VERDE_MEDIO]), legend=alt.Legend(title=None, orient="top")),
        tooltip=["nome", "marco", alt.Tooltip("nota:Q", format=".2f")])
    return (linha + pontos).properties(height=max(120, 30 * len(df)))
