# views/stock.py
import streamlit as st
from lib import db
import sqlite3

# ========= DDL =========
DDL_STOCK = """
CREATE TABLE IF NOT EXISTS stock_items (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  pieza      TEXT    NOT NULL UNIQUE,
  cantidad   INTEGER NOT NULL DEFAULT 0,
  created_at TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_stock_items_pieza ON stock_items(pieza);
"""

def _ensure_tables():
    with db.get_conn() as c:
        c.executescript(DDL_STOCK)

# ========= SQL helpers =========
def _add_item(pieza: str, cantidad_inicial: int = 0):
    pieza = (pieza or "").strip()
    if not pieza:
        return
    cant = max(0, int(cantidad_inicial))
    with db.get_conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO stock_items(pieza, cantidad) VALUES (?, ?)",
            (pieza, cant),
        )
        if cant > 0:
            c.execute("UPDATE stock_items SET cantidad=? WHERE pieza=?", (cant, pieza))

def _delete_item(item_id: int):
    with db.get_conn() as c:
        c.execute("DELETE FROM stock_items WHERE id=?", (int(item_id),))

def _rename_item(item_id: int, nuevo_nombre: str) -> tuple[bool, str | None]:
    nuevo = (nuevo_nombre or "").strip()
    if not nuevo:
        return False, "El nombre no puede estar vacío."
    try:
        with db.get_conn() as c:
            c.execute("UPDATE stock_items SET pieza=? WHERE id=?", (nuevo, int(item_id)))
        return True, None
    except sqlite3.IntegrityError:
        return False, "Ese nombre ya existe en el stock."

def _get_items(search: str | None = None, order_by: str = "pieza", order_dir: str = "ASC"):
    q = "SELECT id, pieza, cantidad FROM stock_items"
    args = []
    if search and search.strip():
        q += " WHERE pieza LIKE ?"
        args.append(f"%{search.strip()}%")

    if order_by == "cantidad":
        q += f" ORDER BY cantidad {order_dir}, UPPER(pieza) ASC"
    else:
        q += f" ORDER BY UPPER(pieza) {order_dir}"

    with db.get_conn() as c:
        rows = c.execute(q, tuple(args)).fetchall()
    return [dict(r) for r in rows]

def _add_move(item_id: int, delta: int):
    with db.get_conn() as c:
        cur = c.execute("SELECT cantidad FROM stock_items WHERE id=?", (int(item_id),)).fetchone()
        if not cur:
            return
        actual = int(cur["cantidad"])
        aplicado = int(delta)
        if aplicado < 0 and actual + aplicado < 0:
            aplicado = -actual
        nuevo = actual + aplicado
        c.execute("UPDATE stock_items SET cantidad=? WHERE id=?", (nuevo, int(item_id)))

# ========= UI =========
def render():
    _ensure_tables()

    st.title("Stock")

    # ---- Alta de pieza ----
    st.subheader("Agregar pieza")
    ca, cb, cc = st.columns([2.5, 1.0, 0.9])
    pieza_new = ca.text_input("Nombre de pieza", value="", placeholder="Ej: Aro acero 8mm")
    cant_new  = cb.number_input("Cantidad inicial", min_value=0, step=1, value=0)
    if cc.button("➕ Agregar", use_container_width=True):
        if (pieza_new or "").strip():
            _add_item(pieza_new, int(cant_new))
            st.success("Pieza cargada.")
            st.rerun()
        else:
            st.warning("Ingresá un nombre de pieza.")

    st.markdown("---")

    # ---- Buscador + Orden ----
    colb1, colb2, colb3 = st.columns([1.7, 1.0, 1.0])
    search = colb1.text_input("Buscar", value="", placeholder="Filtrar por nombre…")

    orden_label = colb2.selectbox(
        "Ordenar por",
        options=["Nombre (A→Z)", "Cantidad (↓)", "Cantidad (↑)"],
        index=0,
    )
    if orden_label.startswith("Nombre"):
        order_by, order_dir = "pieza", "ASC"
    elif "Cantidad (↓)" in orden_label:
        order_by, order_dir = "cantidad", "DESC"
    else:
        order_by, order_dir = "cantidad", "ASC"

    items = _get_items(search, order_by=order_by, order_dir=order_dir)
    total_items = len(items)
    total_unidades = sum(int(i["cantidad"]) for i in items)
    colb3.markdown(f"**Ítems:** {total_items}  \n**Unidades:** {total_unidades}")

    if not items:
        st.info("No hay piezas cargadas.")
        return

    # ---- Encabezados ----
    head = st.columns([2.5, 1.0, 0.8, 0.4, 0.4, 0.4])
    head[0].markdown("**Pieza**")
    head[1].markdown("**Stock**")
    head[2].markdown("**Δ**")
    head[3].markdown("**OK**")
    head[4].markdown("**✏️**")
    head[5].markdown("**🗑**")

    editing_id = st.session_state.get("stock_editing_id")
    editing_val = st.session_state.get("stock_editing_val")

    for it in items:
        iid = int(it["id"])

        with st.form(f"form_{iid}", clear_on_submit=True):
            c1, c2, c3, c4, c5, c6 = st.columns([2.5, 1.0, 0.8, 0.4, 0.4, 0.4])

            # Pieza o edición inline
            if editing_id == iid:
                nuevo_nombre = c1.text_input(
                    "Nuevo nombre",
                    value=editing_val if editing_val is not None else it["pieza"],
                    key=f"edit_name_{iid}",
                    label_visibility="collapsed",
                )
            else:
                c1.write(it["pieza"])

            # Stock
            c2.write(f"{int(it['cantidad'])}")

            # Campo delta
            delta = c3.number_input(
                "Δ",
                value=0,
                step=1,
                format="%d",
                key=f"delta_{iid}",
                label_visibility="collapsed",
            )

            # ✅ aplicar
            aplicar = c4.form_submit_button("✅")

            if aplicar and int(delta) != 0:
                _add_move(iid, int(delta))
                st.rerun()

            # Editar / Guardar
            if editing_id == iid:
                guardar = c5.form_submit_button("💾")
                cancelar = c6.form_submit_button("✖️")
                if guardar:
                    ok, err = _rename_item(iid, st.session_state.get(f"edit_name_{iid}", "").strip())
                    if ok:
                        st.success("Nombre actualizado.")
                        st.session_state.pop("stock_editing_id", None)
                        st.session_state.pop("stock_editing_val", None)
                        st.rerun()
                    else:
                        st.error(err or "No se pudo actualizar el nombre.")
                if cancelar:
                    st.session_state.pop("stock_editing_id", None)
                    st.session_state.pop("stock_editing_val", None)
                    st.rerun()
            else:
                editar = c5.form_submit_button("✏️")
                eliminar = c6.form_submit_button("🗑")
                if editar:
                    st.session_state["stock_editing_id"] = iid
                    st.session_state["stock_editing_val"] = it["pieza"]
                    st.rerun()
                if eliminar:
                    _delete_item(iid)
                    st.rerun()
