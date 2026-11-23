import streamlit as st
import ficha as F
import ui

user = ui.pagina("Visualização de pendências")
d = ui.dados()
ui.rodape_atualizacao(d)
vis, desc = ui.filtros(F.pessoas_visiveis(d, user), "pend")
ui.aviso_tag()
if vis.empty:
    st.info("Nenhum colaborador disponível.")
    st.stop()

det = F.andamento(d, vis)
ver_gpc = bool(user["perfil"] == "rh" or user.get("pode_ver_texto"))
cols_status = [c for c in det.columns if c.split("_")[0].isdigit() and (ver_gpc or not c.endswith("gpc"))]

total_pend = int((det[cols_status] == "Pendente").sum().sum())
pessoas_pend = int(det[cols_status].apply(lambda r: (r == "Pendente").any(), axis=1).sum())
k = st.columns(3)
k[0].metric("Colaboradores no recorte", len(det))
k[1].metric("Com alguma pendência", pessoas_pend)
k[2].metric("Etapas pendentes", total_pend)

so_pend = st.toggle("Mostrar só quem tem alguma pendência", value=False)
if so_pend:
    det = det[det[cols_status].apply(lambda r: (r == "Pendente").any(), axis=1)]
rot = {f"{m}_{p}": f"{m}d · {F.ROTULO_PAPEL[p]}" for m in (45, 90) for p in F.PAPEIS}
tabela = det[["nome", "cargo", "area", "gestor"] + cols_status].rename(
    columns={"nome": "Colaborador", "cargo": "Cargo", "area": "Área", "gestor": "Gestor", **rot})
for c in rot.values():
    if c in tabela:
        tabela[c] = tabela[c].map({"Concluída": "✅ Concluída", "Pendente": "⏳ Pendente"})
st.caption(f"{len(tabela)} colaboradores")
st.dataframe(tabela, use_container_width=True, hide_index=True)
st.caption("Pendente = a etapa ainda não foi respondida. Concluída = há respostas registradas para o marco.")
