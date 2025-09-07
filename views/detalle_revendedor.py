# views/detalle_revendedor.py
import streamlit as st
import pandas as pd
from datetime import date, datetime
from lib import db

def render():
    # Ancla para el botón "↑ Subir"
    st.markdown('<a id="top"></a>', unsafe_allow_html=True)

    rid = st.query_params.get("id")
    try:
        rid = int(rid) if rid is not None else None
    except Exception:
        rid = None

    rev = db.get_revendedor(rid) if rid else None
    if not rev:
        st.error("Revendedor no encontrado.")
        if st.button("⬅ Volver a Revendedores"):
            st.query_params.update({"page": "revendedores"})
            st.rerun()
        return

    # Título + saldo
    st.title(f"Detalle de cuenta — {rev['nombre']}")
    st.markdown(
        f"**ID:** {rev['id']} &nbsp; | &nbsp; {formatear_balance(rev['balance'])}",
        unsafe_allow_html=True
    )

    # -------- Agregar movimiento --------
    st.markdown("---")
    st.subheader("Agregar movimiento")

    with st.form("form_mov_add", clear_on_submit=True):
        c1, c2, c3, c4, c5 = st.columns([1, 3, 1.2, 1.2, 1.2])
        with c1:
            tipo = st.selectbox("Tipo", ["pago", "devolucion"])
        with c2:
            detalle = st.text_input("Detalle")
        with c3:
            fecha_sel = st.date_input("Fecha", value=date.today())
        with c4:
            monto = st.number_input(
                "Monto", min_value=0.0, step=100.0, value=0.0, format="%.2f"
            )
        with c5:
            medio = st.selectbox("Medio de pago", ["MP", "Efectivo"])

        ok = st.form_submit_button("Guardar")
        if ok:
            try:
                db.add_movimiento(
                    rev_id=rev["id"],
                    tipo=tipo,
                    detalle=detalle,
                    cantidad=0,
                    monto=monto,
                    fecha=fecha_sel.strftime("%Y-%m-%d"),  # guardo ISO
                    medio_pago=medio,
                )
                st.success("Movimiento guardado.")
                st.rerun()
            except Exception as e:
                st.warning(f"No se pudo guardar: {e}")

    # -------- Edición (si se eligió modificar) --------
    edit_id = st.session_state.get("edit_mov_id")
    if edit_id:
        data = db.get_movimiento(edit_id)
        if data:
            st.markdown("---")
            st.subheader("Modificar movimiento")
            with st.form("form_mov_edit", clear_on_submit=False):
                c1, c2, c3, c4, c5 = st.columns([1, 3, 1.2, 1.2, 1.2])
                with c1:
                    tipo_e = st.selectbox(
                        "Tipo",
                        ["pago", "devolucion", "entrega"],
                        index=["pago", "devolucion", "entrega"].index(data["tipo"]),
                    )
                with c2:
                    detalle_e = st.text_input("Detalle", value=data["detalle"])
                with c3:
                    try:
                        d0 = datetime.strptime(data["fecha"], "%Y-%m-%d").date()
                    except Exception:
                        d0 = date.today()
                    fecha_e = st.date_input("Fecha", value=d0)
                with c4:
                    monto_e = st.number_input(
                        "Monto",
                        min_value=0.0,
                        step=100.0,
                        value=float(data["monto"]),
                        format="%.2f",
                    )
                with c5:
                    medio_e = st.selectbox(
                        "Medio de pago", ["MP", "Efectivo", ""], index=_medio_idx(data.get("medio_pago"))
                    )

                cA, cB = st.columns([1, 1])
                save = cA.form_submit_button("Guardar cambios")
                cancel = cB.form_submit_button("Cancelar")
                if save:
                    try:
                        db.update_movimiento(
                            edit_id,
                            fecha=fecha_e.strftime("%Y-%m-%d"),
                            tipo=tipo_e,
                            detalle=detalle_e,
                            cantidad=int(data.get("cantidad") or 0),
                            monto=float(monto_e),
                            medio_pago=(None if medio_e == "" else medio_e),
                        )
                        st.success("Movimiento actualizado.")
                        st.session_state.edit_mov_id = None
                        st.rerun()
                    except Exception as e:
                        st.warning(f"No se pudo actualizar: {e}")
                elif cancel:
                    st.session_state.edit_mov_id = None
                    st.rerun()

    # -------- Movimientos --------
    st.markdown("---")
    st.subheader("Movimientos")

    movs = db.get_movimientos(rev["id"])
    if not movs:
        st.info("Sin movimientos.")
    else:
        df = pd.DataFrame(movs)
        cols = ["entrega_nro", "tipo", "detalle", "fecha", "monto", "medio_pago", "id"]
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        # mostrar fecha dd/mm/aa
        try:
            df["fecha_fmt"] = pd.to_datetime(df["fecha"], errors="coerce").dt.strftime("%d/%m/%y")
        except Exception:
            df["fecha_fmt"] = df["fecha"]

        # Header manual
        header = st.columns([0.8, 1.2, 3, 1.3, 1.2, 1.3, 1.1])
        header[0].markdown("**N°**")
        header[1].markdown("**Tipo**")
        header[2].markdown("**Detalle**")
        header[3].markdown("**Fecha**")
        header[4].markdown("**Monto**")
        header[5].markdown("**Medio de pago**")
        header[6].markdown("**Modificar**")

        for _, row in df.iterrows():
            c0, c1, c2, c3, c4, c5, c6 = st.columns([0.8, 1.2, 3, 1.3, 1.2, 1.3, 1.1])
            c0.write("" if pd.isna(row["entrega_nro"]) else int(row["entrega_nro"]))
            c1.write(row["tipo"])
            c2.write(row["detalle"])
            c3.write(row["fecha_fmt"])
            c4.write(f"{row['monto']:,.0f}" if pd.notna(row["monto"]) else "")
            c5.write("" if pd.isna(row["medio_pago"]) else row["medio_pago"])
            if c6.button("✏️", key=f"edit_{int(row['id'])}"):
                st.session_state.edit_mov_id = int(row["id"])
                st.rerun()

    # -------- Barra flotante fija abajo (centrada, sin pestaña nueva) --------
    st.markdown("""
<style>
.block-container { padding-bottom: 96px; }

/* Barra flotante */
#fixed-actions{
  position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
  z-index: 10000; background: rgba(15,15,20,.92);
  padding: 8px 12px; border-radius: 10px;
  border: 1px solid rgba(255,255,255,.15);
  display: flex; gap: 10px;
}
#fixed-actions a{
  text-decoration: none; background: #2b2f3a; color: #fff;
  padding: 6px 12px; border-radius: 8px;
  border: 1px solid rgba(255,255,255,.15);
}
#fixed-actions a:hover{ filter: brightness(1.15); }
</style>
<div id="fixed-actions">
  <a href="?page=revendedores" target="_self">⬅ Volver a Revendedores</a>
  <a href="#top" target="_self">↑ Subir</a>
</div>
""", unsafe_allow_html=True)

def _medio_idx(val):
    if val in ("MP", "Efectivo"): 
        return ["MP", "Efectivo", ""].index(val)
    return 2  # ""

def formatear_balance(bal: float) -> str:
    if bal < 0:
        return f"<span style='color:#ef4444;'>Saldo: ${bal:,.0f}</span>"
    if bal > 0:
        return f"<span style='color:#22c55e;'>Saldo: ${bal:,.0f}</span>"
    return "<span style='color:#22c55e;'>AL DÍA</span>"
