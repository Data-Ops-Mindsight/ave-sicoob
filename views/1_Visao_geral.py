import streamlit as st
import auth
import ficha as F
import pdf
import ui

user = ui.pagina("Visão geral")
d = ui.dados()
ui.rodape_atualizacao(d)
vis, desc = ui.filtros(F.pessoas_visiveis(d, user), "geral")
ui.aviso_tag()
if vis.empty:
    st.info("Nenhum colaborador disponível para o seu escopo (ou ainda não há dados coletados).")
    st.stop()

ver_texto = bool(user["perfil"] == "rh" or user.get("pode_ver_texto"))
ind = F.indicadores(d, vis, ver_texto)
a = ind["andamento"]
n = lambda m, k: int(a[(a.marco == m) & (a.papel == "gestor")][k].sum())
e = ind["evolucao"]
c = st.columns(4)
c[0].metric("Colaboradores em experiência", ind["total"])
c[1].metric("Avaliação do gestor concluída · 45d", n(45, "concluida"))
c[2].metric("Avaliação do gestor concluída · 90d", n(90, "concluida"))
c[3].metric("Pendências (todas as etapas)", int(a["pendente"].sum()))

st.subheader("Andamento por marco e visão")
ch = ui.barras_status(a)
if ch is not None:
    st.altair_chart(ch, use_container_width=True)

por_comp = st.toggle("Analisar por competências", value=True, key="geral_por_comp",
                     help="Ligado: médias por competência (veja a aba Competências). Desligado: médias por pergunta.")
st.subheader("Médias por competência" if por_comp else "Médias por pergunta")
m = ind["medias"] if por_comp else F.indicadores(d, vis, ver_texto, por_competencia=False)["medias"]
if not m.empty:
    pv = m.pivot_table(index="competencia", columns=["marco", "papel"], values="nota", sort=False).round(2)
    pv.columns = [f"{mm}d · {F.ROTULO_PAPEL[pp]}" for mm, pp in pv.columns]
    pv.index.name = "Competência" if por_comp else "Pergunta"
    st.dataframe(pv, use_container_width=True)
    if not por_comp:
        st.caption("Gestor e colaborador respondem perguntas diferentes, por isso cada pergunta aparece só na coluna da sua visão.")

st.subheader("Evolução do 45 ao 90 dias")
mel = ind["melhoraram"]
if not e["n"]:
    st.caption("Ainda não há colaboradores com os dois marcos avaliados pelo gestor.")
else:
    k = st.columns(3)
    k[0].metric("Com os dois marcos avaliados", e["n"])
    k[1].metric("Média do gestor 45d → 90d", f"{e['media_45']:.1f} → {e['media_90']:.1f}".replace(".", ","))
    k[2].metric("Colaboradores que melhoraram", f"{e['melhoraram']} de {e['n']}")
    st.markdown("#### Quem melhorou")
    if mel.empty:
        st.caption("Nenhum colaborador teve média maior no 90º dia em relação ao 45º.")
    else:
        ch = ui.halteres_melhora(mel)
        st.altair_chart(ch, use_container_width=True)
        t = mel.rename(columns={"nome": "Colaborador", "cargo": "Cargo", "area": "Área", "gestor": "Gestor",
                                "media_45": "Média 45d", "media_90": "Média 90d", "variacao": "Variação"})
        st.dataframe(t, use_container_width=True, hide_index=True, column_config={
            "Média 45d": st.column_config.NumberColumn(format="%.2f"),
            "Média 90d": st.column_config.NumberColumn(format="%.2f"),
            "Variação": st.column_config.NumberColumn(format="+%.2f")})
        st.caption("Comparação da média das notas dadas pelo gestor no 45º e no 90º dia.")

if ver_texto and not ind["decisoes"].empty:
    st.subheader("Decisões do GPC")
    st.dataframe(ind["decisoes"], use_container_width=True, hide_index=True)

st.divider()
if user["perfil"] == "rh" or user.get("pode_exportar"):
    st.subheader("Exportar PDF")
    st.caption(f"Recorte atual: {desc or 'todos os colaboradores do seu escopo'}")
    b1, b2 = st.columns(2)
    b1.download_button("⬇ Resumo executivo", data=pdf.pdf_executivo(ind, desc, user["usuario"], ver_texto),
                       file_name="AVE_resumo_executivo.pdf", mime="application/pdf",
                       on_click=auth.registrar, args=(user["usuario"], "exportar_pdf_executivo", desc))
    if b2.button(f"Gerar relatório consolidado ({len(vis)} fichas)"):
        with st.spinner("Gerando PDF em lote…"):
            fichas = [F.ficha(d, p, user) for p in vis.pessoa_id]
            st.session_state["lote"] = pdf.pdf_lote([x for x in fichas if x], desc, user["usuario"])
        auth.registrar(user["usuario"], "exportar_pdf_lote", f"{len(vis)} fichas | {desc}")
    if st.session_state.get("lote"):
        b2.download_button("⬇ Baixar relatório consolidado", data=st.session_state["lote"],
                           file_name="AVE_relatorio_consolidado.pdf", mime="application/pdf")
else:
    st.caption("Seu perfil não tem permissão de exportação.")
