import streamlit as st
import auth
import brand as B
import ficha as F
import pdf
import ui

user = ui.pagina("Ficha individual")
d = ui.dados()
ui.rodape_atualizacao(d)
vis, _ = ui.filtros(F.pessoas_visiveis(d, user), "ficha")
ui.aviso_tag()
if vis.empty:
    st.info("Nenhum colaborador disponível.")
    st.stop()

rot = {r.pessoa_id: f"{r.nome} — {r.cargo or 's/ cargo'}" for r in vis.itertuples()}
pid = st.selectbox("Colaborador", list(rot), format_func=rot.get)
por_comp = st.toggle("Analisar por competências", value=True, key="ficha_por_comp",
                     help="Ligado: as perguntas são agrupadas em competências (veja a aba Competências). "
                          "Desligado: a análise é feita pergunta a pergunta.")
f = F.ficha(d, pid, user, por_competencia=por_comp)  # None se fora do escopo (defesa em profundidade)
if f is None:
    st.error("Fora do seu escopo.")
    st.stop()
auth.registrar(user["usuario"], "ver_ficha", pid)

p = f["pessoa"]
c = st.columns(4)
c[0].markdown(f"**Cargo**  \n{p.get('cargo') or '—'}")
c[1].markdown(f"**Área**  \n{p.get('area') or '—'}")
c[2].markdown(f"**Gestor**  \n{p.get('gestor_nome') or '—'}")
c[3].markdown(f"**E-mail**  \n{p.get('email') or '—'}")

if user["perfil"] == "rh" or user.get("pode_exportar"):
    st.download_button("⬇ PDF individual", data=pdf.pdf_individual(f, user["usuario"]),
                       file_name=f"AVE_{pid}.pdf", mime="application/pdf",
                       on_click=auth.registrar, args=(user["usuario"], "exportar_pdf_individual", pid))

fmt = lambda v: "—" if v is None else f"{v:.1f}".replace(".", ",")
ev = F.evolucao_competencias(f)

st.subheader("Resumo")
g45, g90 = f["marcos"][45]["gestor"]["media"], f["marcos"][90]["gestor"]["media"]
a45, a90 = f["marcos"][45]["colaborador"]["media"], f["marcos"][90]["colaborador"]["media"]
k = st.columns(4)
k[0].metric("Gestor · 45 dias", fmt(g45))
k[1].metric("Gestor · 90 dias", fmt(g90), delta=None if None in (g45, g90) else f"{g90 - g45:+.1f}".replace(".", ","))
k[2].metric("Autoavaliação · 45 dias", fmt(a45))
k[3].metric("Autoavaliação · 90 dias", fmt(a90), delta=None if None in (a45, a90) else f"{a90 - a45:+.1f}".replace(".", ","))

if not por_comp:
    st.caption("Análise por perguntas: os formulários de cada marco têm perguntas diferentes, por isso a evolução "
               "45 → 90 dias só é calculada por competência (ligue a chave acima).")
elif not ev.empty and ev["marco"].nunique() > 1:
    st.markdown("#### Evolução por competência (45 → 90 dias)")
    visao = st.radio("Visão", ["Gestor", "Autoavaliação"], horizontal=True, key="visao_evol")
    papel = "gestor" if visao == "Gestor" else "colaborador"
    sub = ev[ev.papel == papel]
    # só competências presentes nos dois marcos
    ok = sub.groupby("competencia")["marco"].nunique()
    sub = sub[sub.competencia.isin(ok[ok > 1].index)]
    ch = ui.barras_evolucao(sub)
    if ch is not None:
        st.altair_chart(ch, use_container_width=True)
    else:
        st.caption("Sem competências em comum entre os dois marcos para esta visão.")

st.subheader("Detalhe por marco")
tabs = st.tabs([f"Marco {m} dias" for m in f["marcos"]])
for tab, (m, b) in zip(tabs, f["marcos"].items()):
    with tab:
        cols = st.columns(3)
        for col, papel in zip(cols, F.PAPEIS):
            bl = b[papel]
            with col.container(border=True):
                st.markdown(f"<div style='color:{B.SERIES[papel]};font-weight:700'>{F.ROTULO_PAPEL[papel]}</div>",
                            unsafe_allow_html=True)
                st.markdown(ui.chip(bl["status"]), unsafe_allow_html=True)
                if papel != "gpc":
                    st.metric("Média", fmt(bl["media"]))
        comp = f["comparativo"][f["comparativo"].marco == m]
        if not comp.empty:
            st.markdown("#### Gestor × Autoavaliação por " + ("competência" if por_comp else "pergunta"))
            if not por_comp:
                st.caption("O gestor e o colaborador respondem perguntas diferentes: cada barra é uma pergunta, na cor da sua visão.")
            ch = ui.barras_comparativo(comp, por_pergunta=not por_comp)
            if ch is not None:
                st.altair_chart(ch, use_container_width=True)

        st.markdown("#### Respostas")
        sub = st.tabs([F.ROTULO_PAPEL[x] for x in F.PAPEIS])
        for st_tab, papel in zip(sub, F.PAPEIS):
            bl = b[papel]
            with st_tab:
                if bl["status"] == "Restrito":
                    st.info("Não disponível para o seu perfil.")
                    continue
                if bl["status"] == "Pendente" and not bl["itens"] and not bl["abertas"]:
                    st.caption("Etapa ainda não preenchida.")
                    continue
                if bl["itens"]:
                    st.markdown(ui.html_escolha(bl["itens"]), unsafe_allow_html=True)
                if bl["abertas"]:
                    st.markdown("##### Respostas abertas")
                    st.markdown(ui.html_abertas(bl["abertas"]), unsafe_allow_html=True)
                if not (bl["itens"] or bl["abertas"]):
                    st.caption("Sem respostas registradas.")
