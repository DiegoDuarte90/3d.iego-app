# views/revendedores.py
import streamlit as st
from lib import db

def render():
    st.title("Listado de Revendedores")

    # --- estados de UI ---
    edit_id = st.session_state.get("edit_rev_id")
    delete_id = st.session_state.get("delete_rev_id")

    # Buscador + botón Nuevo
    col1, col2 = st.columns([3, 1])
    with col1:
        q = st.text_input("Buscador", placeholder="Escriba aquí un nombre...")
    with col2:
        if st.button("➕ Nuevo", use_container_width=True, key="btn_nuevo_rev"):
            st.session_state.show_form_rev = not st.session_state.get("show_form_rev", False)

    # Form para crear revendedor (NO redirige al detalle)
    if st.session_state.get("show_form_rev", False):
        with st.form("form_nuevo_revendedor", clear_on_submit=True):
            nombre = st.text_input("Nombre del nuevo revendedor")
            submitted = st.form_submit_button("Guardar")
            if submitted:
                try:
                    rid = db.add_revendedor(nombre)
                    st.success(f"✅ Revendedor '{nombre}' creado (ID {rid}).")
                    st.session_state.show_form_rev = False
                    st.rerun()
                except Exception as e:
                    st.warning(f"⚠ No se pudo crear: {e}")

    # Bloque de edición (si corresponde)
    if edit_id:
        rev = _safe_get_rev(edit_id)
        if rev:
            st.markdown("---")
            st.subheader("Modificar revendedor")
            with st.form("form_edit_rev", clear_on_submit=False):
                nuevo_nombre = st.text_input("Nombre", value=rev["nombre"])
                c1, c2 = st.columns([1,1])
                guardar = c1.form_submit_button("Guardar cambios")
                cancelar = c2.form_submit_button("Cancelar")
                if guardar:
                    try:
                        db.update_revendedor(edit_id, nuevo_nombre)
                        st.success("Cambios guardados.")
                        st.session_state.edit_rev_id = None
                        st.rerun()
                    except Exception as e:
                        st.warning(f"No se pudo actualizar: {e}")
                elif cancelar:
                    st.session_state.edit_rev_id = None
                    st.rerun()

    # Aviso de borrado (confirmación global)
    if delete_id:
        rev = _safe_get_rev(delete_id)
        if rev:
            st.markdown("---")
            st.error(f"¿Borrar al revendedor **{rev['nombre']}** (ID {rev['id']})? "
                     "Se eliminarán también sus movimientos.")
            c1, c2 = st.columns([1,1])
            if c1.button("✅ Confirmar borrado", key="confirm_delete_btn"):
                try:
                    db.delete_revendedor(delete_id)
                    st.success("Revendedor eliminado.")
                    st.session_state.delete_rev_id = None
                    st.rerun()
                except Exception as e:
                    st.warning(f"No se pudo borrar: {e}")
            if c2.button("Cancelar", key="cancel_delete_btn"):
                st.session_state.delete_rev_id = None
                st.rerun()

    # Obtener lista de revendedores
    data = db.get_revendedores(q)
    if not data:
        st.warning("No se encontraron revendedores.")
        return

    # Tabla: ID | Nombre | Balance | Detalles | Acciones
    st.markdown("### Resultados")
    header = st.columns([0.6, 3, 2, 1, 1.8])
    header[0].markdown("**ID**")
    header[1].markdown("**Nombre**")
    header[2].markdown("**Balance**")
    header[3].markdown("**Detalles**")
    header[4].markdown("**Acciones**")

    for i, r in enumerate(data):
        c0, c1, c2, c3, c4 = st.columns([0.6, 3, 2, 1, 1.8])
        c0.write(r["id"])
        c1.write(r["nombre"])
        bal = r.get("balance", 0.0)
        if bal < 0:
            c2.markdown(f"<span style='color:#ef4444;'>${bal:,.0f}</span>", unsafe_allow_html=True)
        elif bal > 0:
            c2.markdown(f"<span style='color:#22c55e;'>${bal:,.0f}</span>", unsafe_allow_html=True)
        else:
            c2.markdown("<span style='color:#22c55e;'>AL DÍA</span>", unsafe_allow_html=True)

        # Ir a detalle
        if c3.button("➡", key=f"det_{r['id']}"):
            st.query_params.update({"page": "detalle", "id": str(r['id'])})
            st.rerun()

        # Acciones: Modificar / Borrar
        ac1, ac2 = c4.columns(2)
        if ac1.button("✏️", key=f"edit_btn_{r['id']}"):
            st.session_state.edit_rev_id = r["id"]
            st.rerun()
        if ac2.button("🗑️", key=f"del_btn_{r['id']}"):
            st.session_state.delete_rev_id = r["id"]
            st.rerun()

        # Separador entre filas
        if i < len(data) - 1:
            st.markdown(
                "<hr style='margin:6px 0; border:0; border-top:1px solid rgba(255,255,255,0.15);'>",
                unsafe_allow_html=True
            )

def _safe_get_rev(rid: int):
    try:
        return db.get_revendedor(rid)
    except Exception:
        return None
