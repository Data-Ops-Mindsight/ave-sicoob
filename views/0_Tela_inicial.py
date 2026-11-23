import streamlit as st
import api
import auth
import coletor
import db
import ficha as F
import ui

user = ui.pagina("Tela inicial")
rh = user["perfil"] == "rh"
st.markdown(f"Olá, **{user['nome']}**. Este painel reúne, em um só lugar, a avaliação do gestor, a autoavaliação e o "
            f"parecer do RH (GPC) da **{ui.cfg()['rodada_nome']}**, por marco de 45 e 90 dias.")

st.subheader("Atualização dos dados")
with st.container(border=True):
    ult = db.get_meta("ultima_coleta_respostas")
    c1, c2 = st.columns([2, 1])
    c1.metric("Última atualização de respostas e notas", db.fmt_ts(ult))
    c2.metric("Última atualização de participantes", db.fmt_ts(db.get_meta("ultima_coleta_participantes")))
    falha = db.df("SELECT ts, tipo FROM coleta_log WHERE ok=0 ORDER BY ts DESC LIMIT 1")
    if not falha.empty and (not ult or falha.iloc[0]["ts"] > ult):
        st.warning(f"A última tentativa de coleta ({db.fmt_ts(falha.iloc[0]['ts'])}) falhou. "
                   "O painel segue exibindo os últimos dados válidos.")
    if rh and ui.erro_secrets():
        st.error(ui.erro_secrets())
    if rh:
        if not api.tem_token():
            st.error("Token do Mindsight não configurado no servidor (planilha de tokens no `.env` ou `MINDSIGHT_TOKEN`).")
        else:
            falta = coletor.espera_restante()
            if st.button("🔄 Atualizar respostas e notas", type="primary", disabled=falta > 0):
                with st.spinner("Buscando participantes, respostas e pares no Mindsight…"):
                    ok, msg = coletor.atualizar_manual()
                auth.registrar(user["usuario"], "atualizar_dados", "ok" if ok else "falha/aguarde")
                if ok:
                    st.cache_data.clear()
                    st.success(msg)
                    st.rerun()
                else:
                    st.warning(msg)
            lib = coletor.liberado_em()
            if falta > 0 and lib:
                st.caption(f"Nova atualização liberada às {lib:%H:%M} (em {coletor.fmt_espera(falta)}).")
            st.caption(f"Os dados **só** são atualizados quando alguém clica neste botão — não há atualização automática. "
                       f"Intervalo mínimo entre atualizações: {ui.cfg()['espera_atualizacao_min']} minutos.")
    else:
        st.caption("A atualização dos dados é feita pelo RH, pelo botão desta tela (não há atualização automática).")

st.subheader("Quem aparece no painel")
tag = ui.cfg().get("tag_em_experiencia", "Em experiência")
st.info(f"Aparecem **somente os colaboradores que têm a tag “{tag}”** na rodada do Mindsight (e que tenham "
        "avaliações na rodada). Gestores, avaliadores do GPC e qualquer pessoa sem essa tag não são listados, "
        "mesmo que tenham respondido formulários. " + ("" if rh else "Além disso, você só vê as pessoas do seu escopo."))

st.subheader("O que você encontra em cada aba")
abas = [
    ("📊 Visão geral", "Indicadores do recorte escolhido: andamento por marco, médias por competência, evolução do 45 ao "
     "90 dias e **quem melhorou**. Exportação do resumo executivo e do relatório consolidado em PDF."),
    ("👤 Ficha individual", "Tudo de um colaborador: resumo dos marcos, gráficos de evolução e de gestor × autoavaliação, "
     "e as respostas organizadas por competência, com justificativas e parecer do RH."),
    ("⏳ Visualização de pendências", "Lista de colaboradores com o status (Concluída ou Pendente) de cada etapa — gestor, "
     "autoavaliação e GPC — em cada marco, com filtro para ver só quem tem pendência."),
    ("🧩 Competências", "Explica o que são as competências, como as perguntas foram agrupadas nelas e quais perguntas "
     "compõem cada uma."),
]
if rh:
    abas.append(("🔐 Painel Admin", "Criação, edição e revogação de acessos dos BPs (pessoas, áreas e cargos permitidos, "
                 "texto, exportação e validade) e o histórico dessas ações."))
cols = st.columns(2)
for i, (t, d) in enumerate(abas):
    with cols[i % 2].container(border=True):
        st.markdown(f"**{t}**")
        st.write(d)

if not rh:
    st.info("Seu acesso é restrito às pessoas, áreas e cargos definidos pelo RH. "
            + ("" if user.get("pode_ver_texto") else "Justificativas, textos livres e parecer do RH não estão habilitados no seu perfil. ")
            + ("" if user.get("pode_exportar") else "A exportação de PDF não está habilitada."))
