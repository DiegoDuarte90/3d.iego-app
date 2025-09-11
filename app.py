# app.py
import streamlit as st
from lib import db
from views import revendedores, detalle_revendedor, entregas, cuentas

st.set_page_config(page_title="3D.IEGO", layout="wide")
db.init_db()

# Sidebar MENÚ
with st.sidebar:
    st.subheader("MENÚ")
    colA = st.button("Revendedores", use_container_width=True)
    colB = st.button("Entregas", use_container_width=True)
    colC = st.button("Cuentas", use_container_width=True)   # ← nuevo
    if colA:
        st.query_params.update({"page": "revendedores"}); st.rerun()
    if colB:
        st.query_params.update({"page": "entregas"}); st.rerun()
    if colC:
        st.query_params.update({"page": "cuentas"}); st.rerun()

page = st.query_params.get("page", "revendedores")
if page == "detalle":
    detalle_revendedor.render()
elif page == "entregas":
    entregas.render()
elif page == "cuentas":                  # ← nuevo
    cuentas.render()
else:
    revendedores.render()
