# views/detalle_revendedor.py
import re
import streamlit as st
import pandas as pd
from datetime import date, datetime
from lib import db

# -----------------------
# Helpers
# -----------------------
def _medio_idx(val):
    opciones = ["MP", "Efectivo", "DEVOLUCION", ""]
    try:
        return opciones.index(val if val in opciones else "")
    except Exception:
        return len(opciones) - 1  # ""

def _monto_con_signo(tipo: str, monto: float) -> float:
    """Para 'devolucion' el monto debe restar (negativo). Para el resto, positivo."""
    tipo = (tipo or "").strip().lower()
    return -abs(monto) if tipo == "devolucion" else abs(monto)

def _fmt_mon(v) -> str:
    try:
        return f"${v:,.0f}".replace(",", ".")
    except Exception:
        return "-"

def formatear_balance(bal: float) -> str:
    if bal < 0:
        return f"<span style='color:#ef4444;'>Saldo: {_fmt_mon(bal)}</span>"
    if bal > 0:
        return f"<span style='color:#22c55e;'>Saldo: {_fmt_mon(bal)}</span>"
    return "<span style='color:#22c55e;'>AL DÍA</span>"

def _parse_entrega_nro_from_detalle(texto: str) -> int | None:
    """
    Intenta extraer el número de entrega desde el detalle, por ejemplo:
    'Entrega N°48', 'entrega 12', 'ENTREGA Nº 7', etc.
    """
    if not texto:
        return None
    m = re.search(r"entrega\s*(?:n[º°o]\s*)?(\d+)", str(texto), flags=re.IGNORECASE)
    return int(m.group(1)) if m else None

# -----------------------
# Modal de detalle de entrega (versión para esta vista)
# -----------------------
def _maybe_open_entrega_dialog_rev():
    """Abre el modal SOLO si fue solicitado por la lupa en esta corrida (detalle_revendedor)."""
    ss = st.session_state
    if not (ss.get("rev_ent_modal_once") and ss.get("rev_modal_entrega_id")):
        return

    try:
        dialog = getattr(st, "dialog")
    except AttributeError:
        dialog = None

    titulo = f"Detalle Entrega N° {ss.get('rev_modal_entrega_nro')}"
    if dialog:
        @dialog(titulo)
        def _dlg():
            _render_modal_detalle_rev(ss["rev_modal_entrega_id"])
        _dlg()
    else:
        st.markdown("""
<style>
#overlay{ position:fixed; z-index:10050; inset:0; background:rgba(0,0,0,.55); }
#modal{
  position:fixed; z-index:10060; left:50%; top:50%;
  transform:translate(-50%,-50%); width:min(820px, 94vw); max-height:80vh; overflow:auto;
  background:#11151a; border:1px solid rgba(255,255,255,.15); border-radius:12px; padding:16px;
}
</style>
<div id="overlay"></div>
<div id="modal"><h4>""" + titulo + """</h4></div>
""", unsafe_allow_html=True)
        _render_modal_detalle_rev(ss["rev_modal_entrega_id"])

    # ¡Clave! evitar reabrir en reruns posteriores
    ss.rev_ent_modal_once = False

def _render_modal_detalle_rev(entrega_id: int):
    try:
        items = db.get_entrega_items(int(entrega_id))
    except Exception:
        items = None

    if not items:
        st.info("Sin ítems.")
    else:
        df = pd.DataFrame(items)[["pieza", "cantidad", "precio", "total"]]
        st.dataframe(df, width="stretch")

    col1, col2 = st.columns([1, 1])
    if col1.button("Cerrar", key="close_ent_modal_rev"):
        # limpiar flags para que no reabra
        st.session_state.rev_ent_modal_once = False
        st.session_state.rev_modal_entrega_id = None
        st.session_state.rev_modal_entrega_nro = None
        st.rerun()

# -----------------------
# Render
# -----------------------
def render():
    # Ancla para el botón "↑ Subir"
    st.markdown('<a id="top"></a>', unsafe_allow_html=True)

    # Estado modal (propio de esta vista)
    ss = st.session_state
    ss.setdefault("rev_ent_modal_once", False)
    ss.setdefault("rev_modal_entrega_id", None)
    ss.setdefault("rev_modal_entrega_nro", None)

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
        f"**ID:** {rev['id']} &nbsp; | &nbsp; {formatear_balance(rev.get('balance', 0.0))}",
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
            monto = st.number_input("Monto", min_value=0.0, step=100.0, value=0.0, format="%.2f")
        with c5:
            medio = st.selectbox("Medio de pago", ["MP", "Efectivo", "DEVOLUCION"])

        ok = st.form_submit_button("Guardar")
        if ok:
            try:
                monto_signed = _monto_con_signo(tipo, float(monto))
                db.add_movimiento(
                    rev_id=rev["id"],
                    tipo=tipo,
                    detalle=detalle,
                    cantidad=0,
                    monto=monto_signed,  # con signo normalizado
                    fecha=fecha_sel.strftime("%Y-%m-%d"),
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
                        value=float(abs(data.get("monto") or 0.0)),
                        format="%.2f",
                    )
                with c5:
                    medio_e = st.selectbox(
                        "Medio de pago", ["MP", "Efectivo", "DEVOLUCION", ""], index=_medio_idx(data.get("medio_pago"))
                    )

                cA, cB = st.columns([1, 1])
                save = cA.form_submit_button("Guardar cambios")
                cancel = cB.form_submit_button("Cancelar")
                if save:
                    try:
                        monto_signed_e = _monto_con_signo(tipo_e, float(monto_e))
                        db.update_movimiento(
                            edit_id,
                            fecha=fecha_e.strftime("%Y-%m-%d"),
                            tipo=tipo_e,
                            detalle=detalle_e,
                            cantidad=int(data.get("cantidad") or 0),
                            monto=monto_signed_e,  # normalizado según tipo
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
        cols = ["entrega_nro", "entrega_id", "tipo", "detalle", "fecha", "monto", "medio_pago", "id"]
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        # mostrar fecha dd/mm/aa
        try:
            df["fecha_fmt"] = pd.to_datetime(df["fecha"], errors="coerce").dt.strftime("%d/%m/%y")
        except Exception:
            df["fecha_fmt"] = df["fecha"]

        # Header manual (agrego 🔎 antes de ✏️/🗑)
        header = st.columns([0.8, 1.2, 3, 1.3, 1.2, 1.3, 0.8, 0.8, 0.8])
        header[0].markdown("**N°**")
        header[1].markdown("**Tipo**")
        header[2].markdown("**Detalle**")
        header[3].markdown("**Fecha**")
        header[4].markdown("**Monto**")
        header[5].markdown("**Medio de pago**")
        header[6].markdown("**🔎**")
        header[7].markdown("**✏️**")
        header[8].markdown("**🗑**")

        for _, row in df.iterrows():
            c0, c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([0.8, 1.2, 3, 1.3, 1.2, 1.3, 0.8, 0.8, 0.8])
            c0.write("" if pd.isna(row["entrega_nro"]) else int(row["entrega_nro"]))
            c1.write(row["tipo"])
            c2.write(row["detalle"])
            c3.write(row["fecha_fmt"])

            # monto con color:
            # - Pagos y Devoluciones -> verde (entradas)
            # - Entregas positivas -> rojo (aumenta deuda)
            # - Resto -> neutro
            monto_val = float(row.get("monto") or 0.0)
            tipo_val = str(row.get("tipo", "")).lower()

            if tipo_val in ("pago", "devolucion") and monto_val != 0:
                c4.markdown(f"<span style='color:#22c55e;'>{_fmt_mon(monto_val)}</span>", unsafe_allow_html=True)
            elif tipo_val == "entrega" and monto_val > 0:
                c4.markdown(f"<span style='color:#ef4444;'>{_fmt_mon(monto_val)}</span>", unsafe_allow_html=True)
            else:
                c4.write(_fmt_mon(monto_val))

            c5.write("" if pd.isna(row["medio_pago"]) else row["medio_pago"])

            # 🔎 ver detalle de entrega — siempre muestro el botón y resuelvo al click
            if c6.button("🔎", key=f"ent_det_{int(row['id'])}"):
                entrega_id = None
                entrega_nro = None

                # 1) entrega_id directo
                if pd.notna(row.get("entrega_id")) and str(row.get("entrega_id")).strip() != "":
                    try:
                        entrega_id = int(row["entrega_id"])
                    except Exception:
                        entrega_id = None

                # 2) entrega_nro en movimiento
                if entrega_id is None and pd.notna(row.get("entrega_nro")) and str(row.get("entrega_nro")).strip() != "":
                    try:
                        entrega_nro = int(row["entrega_nro"])
                    except Exception:
                        entrega_nro = None

                # 3) intentar parsear desde el detalle (p.ej. 'Entrega N°48')
                if entrega_id is None and entrega_nro is None:
                    entrega_nro = _parse_entrega_nro_from_detalle(row.get("detalle", ""))

                # Resolver id usando el historial si hace falta
                if entrega_id is None and entrega_nro is not None:
                    try:
                        hist = db.get_entregas_historial() or []
                        candidatos = [h for h in hist if int(h.get("entrega_nro", -1)) == int(entrega_nro)]
                        if len(candidatos) > 1:
                            candidatos = [h for h in candidatos if (h.get("rev_id") == rev["id"])]
                        if candidatos:
                            entrega_id = int(candidatos[0]["id"])
                    except Exception:
                        entrega_id = None

                if entrega_id:
                    ss.rev_ent_modal_once = True
                    ss.rev_modal_entrega_id = int(entrega_id)
                    ss.rev_modal_entrega_nro = int(entrega_nro) if entrega_nro is not None else int(row.get("entrega_nro") or 0)
                    st.rerun()
                else:
                    st.info("No se encontró la entrega asociada a este movimiento.")

            # editar  <<<<<< CORREGIDO
            if c7.button("✏️", key=f"edit_{int(row['id'])}"):
                st.session_state.edit_mov_id = int(row["id"])
                st.rerun()

            # borrar  <<<<<< CORREGIDO
            if c8.button("🗑", key=f"del_{int(row['id'])}"):
                try:
                    db.delete_movimiento(int(row["id"]))
                    st.success("Movimiento eliminado.")
                    st.rerun()
                except Exception as e:
                    st.warning(f"No se pudo eliminar: {e}")

    # Render del modal SOLO si fue pedido explícitamente en esta corrida
    _maybe_open_entrega_dialog_rev()

    # -------- Barra flotante (Volver / Subir) --------
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
