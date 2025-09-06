import os
from datetime import datetime
import streamlit as st
import pandas as pd

st.set_page_config(page_title="3D.IEGO - Dev", layout="wide")

st.title("3D.IEGO - App de desarrollo")
st.caption("Entorno local • " + datetime.now().strftime("%Y-%m-%d %H:%M"))

with st.sidebar:
    st.subheader("Opciones")
    nombre = st.text_input("Tu nombre", "Diego")
    st.write("Hola,", nombre)

st.success("Si ves esto, Streamlit está funcionando 👌")

st.subheader("Mini demo dataframe")
df = pd.DataFrame({"Item": ["A","B","C"], "Valor":[1,2,3]})
st.dataframe(df, use_container_width=True)

st.subheader("Variables de entorno")
st.code("\\n".join([f"{k}={v}" for k,v in os.environ.items() if k in ["PORT","ENV","DEBUG"]]) or "(sin .env)")
