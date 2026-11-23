"""AVE – Sicoob Cocred. Execute: streamlit run app.py
Este arquivo só faz login e monta o menu; o conteúdo de cada aba está em views/."""
import streamlit as st
import ui

user = ui.boot()

paginas = [
    st.Page("views/0_Tela_inicial.py", title="Tela inicial", default=True),
    st.Page("views/1_Visao_geral.py", title="Visão geral"),
    st.Page("views/2_Ficha_individual.py", title="Ficha individual"),
    st.Page("views/3_Visualizacao_de_pendencias.py", title="Visualização de pendências"),
    st.Page("views/4_Competencias.py", title="Competências")
]
st.navigation(paginas).run()
