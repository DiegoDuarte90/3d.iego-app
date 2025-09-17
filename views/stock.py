# views/stock.py
import streamlit as st
from datetime import date
from lib import db

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
    pieza = pieza.strip()
    if not pieza:
        return
    cant = max(0, int(cantidad_inicial))
    with db.get_conn() as c:
        c.execute("INSERT OR IGNORE INTO stock_items(pieza, cantidad) VALUES (?, ?)", (pieza, cant))
        if cant > 0:
            c.execute("UPDATE stock_items SET cantidad=? WHERE pieza=?", (cant, pieza))

def _delete_item(item_id: int):
    with db.get_conn() as c:
        c.execute("DELETE FROM stock_items WHERE id=?", (int(item_id),))

def _get_items(search: str | None = None):
    q = "SELECT id, pieza, cantidad FROM stock_items"
    args = []
    if search and search.strip():
        q += " WHERE pieza LIKE ?"
        args.append(f"%{search.strip()}%")
    q += " ORDER BY UPPER(pieza)"
    with db.get_conn() as c:
        rows = c.execute(q, tuple(args)).fetchall()
    return [dict(r) for r in rows]

def _add_move(item_id: int, delta: int):
    """Aplica el delta al stock (no baja de 0)."""
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
        if pieza_new.strip():
            _add_item(pieza_new, int(cant_new))
            st.success("Pieza cargada.")
            st.rerun()
        else:
            st.warning("Ingresá un nombre de pieza.")

    st.markdown("---")

    # ---- Buscador + resumen ----
    colb1, colb2 = st.columns([2.0, 1.0])
    search = colb1.text_input("Buscar", value="", placeholder="Filtrar por nombre…")
    items = _get_items(search)
    total_items = len(items)
    total_unidades = sum(int(i["cantidad"]) for i in items)
    colb2.markdown(f"**Ítems:** {total_items} &nbsp; | &nbsp; **Unidades:** {total_unidades}")

    # ---- Listado ----
    if not items:
        st.info("No hay piezas cargadas.")
        return

    head = st.columns([2.6, 1.0, 1.2])
    head[0].markdown("**Pieza**")
    head[1].markdown("**Stock**")
    head[2].markdown("**Acciones**")

    for it in items:
        iid = int(it["id"])
        c1, c2, c3 = st.columns([2.6, 1.0, 1.2])

        # Nombre + stock
        c1.write(it["pieza"])
        c2.write(f"{int(it['cantidad'])}")

        # Botones + / - / borrar
        add_btn, sub_btn, del_btn = c3.columns([0.33, 0.33, 0.34])
        if add_btn.button("➕", key=f"btn_add_{iid}"):
            _add_move(iid, +1)
            st.rerun()
        if sub_btn.button("➖", key=f"btn_sub_{iid}"):
            _add_move(iid, -1)
            st.rerun()
        if del_btn.button("🗑", key=f"del_{iid}"):
            _delete_item(iid)
            st.rerun()
