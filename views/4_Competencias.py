import pandas as pd
import streamlit as st
import ficha as F
import ui
from config import BASE, descricoes_temas

user = ui.pagina("Competências")

st.markdown("""
### O que são as competências
Uma **competência** é um tema (por exemplo, *Comunicação e feedback*) que reúne perguntas dos formulários que avaliam o
**mesmo comportamento**. Elas existem porque o gestor e o colaborador respondem formulários **com perguntas diferentes**
(o colaborador fala de si, “*Comunico-me de forma clara…*”; o gestor fala do colaborador, “*Comunica-se de forma clara…*”),
e os formulários de 45 e de 90 dias também mudam. Sem um tema em comum, não haveria como comparar
**gestor × autoavaliação** nem acompanhar a **evolução do 45º ao 90º dia**.

### Como foi feito o agrupamento
1. Foram lidas as **73 perguntas de múltipla escolha** dos quatro formulários (45 e 90 dias, de gestor e de colaborador).
2. Perguntas que tratam do mesmo comportamento foram reunidas em **12 competências**, mesmo quando o texto é diferente.
3. O vínculo é feito pela **posição da pergunta no formulário** e fica registrado no arquivo `competencias.yaml`.
   Para ajustar um agrupamento basta editar esse arquivo — não é preciso mexer no código.
4. A **nota da competência** é a **média simples** das notas das perguntas do tema, por marco e por visão.
   Escala das respostas: 1 = Discordo Totalmente · 2 = Discordo · 3 = Concordo · 4 = Concordo Totalmente.
5. **Perguntas abertas** e o **parecer do GPC** não têm nota e, por isso, não entram nas competências.

> Este agrupamento é uma **proposta técnica** e deve ser validado pelo RH. Algumas competências existem só em certos
> formulários (por exemplo, *Potencial* é avaliada apenas pelo gestor aos 90 dias) e, nesses casos, não aparecem nos comparativos.

Nas abas **Ficha individual** e **Visão geral** a chave **“Analisar por competências”** permite desligar o agrupamento e
analisar **pergunta a pergunta**.
""")

ref = BASE / "perguntas_rodada.csv"
if not ref.exists():
    st.warning("Arquivo de referência `perguntas_rodada.csv` não encontrado.")
    st.stop()
df = pd.read_csv(ref)
rot = {(45, "gestor"): "45d · Gestor", (45, "colaborador"): "45d · Autoavaliação",
       (90, "gestor"): "90d · Gestor", (90, "colaborador"): "90d · Autoavaliação"}
df["visao"] = [rot[(m, p)] for m, p in zip(df.marco, df.papel)]

st.subheader("Quantas perguntas cada competência reúne")
cob = df.pivot_table(index="competencia", columns="visao", values="ordem", aggfunc="count", fill_value=0)
cob = cob[[c for c in rot.values() if c in cob.columns]]
cob["Total"] = cob.sum(axis=1)
cob.index.name = "Competência"
st.dataframe(cob.sort_values("Total", ascending=False), use_container_width=True)

st.subheader("Perguntas de cada competência")
desc = descricoes_temas()
for comp in sorted(df.competencia.unique()):
    sub = df[df.competencia == comp]
    with st.expander(f"{comp}  ·  {len(sub)} perguntas"):
        if desc.get(comp):
            st.markdown(f"_{desc[comp]}_")
        for visao in rot.values():
            s = sub[sub.visao == visao].sort_values("ordem")
            if s.empty:
                continue
            st.markdown(f"**{visao}**")
            st.markdown("\n".join(f"- {p}" for p in s.pergunta))
