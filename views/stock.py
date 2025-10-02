# views/stock.py
import streamlit as st
from lib import db
import sqlite3
from collections import defaultdict

# ========= DDL base (sin UNIQUE en pieza) =========
DDL_STOCK_BASE = """
CREATE TABLE IF NOT EXISTS stock_items (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  pieza      TEXT    NOT NULL,
  cantidad   INTEGER NOT NULL DEFAULT 0,
  created_at TEXT    DEFAULT (datetime('now')),
  categoria  TEXT,
  subtipo    TEXT
);
CREATE INDEX IF NOT EXISTS idx_stock_items_pieza ON stock_items(pieza);
"""

def _ensure_tables_and_migrate():
    """Crea/actualiza la tabla y asegura unicidad (pieza,categoria,subtipo)."""
    with db.get_conn() as c:
        # 0) Crear tabla si no existe (sin UNIQUE en pieza)
        c.executescript(DDL_STOCK_BASE)

        # 1) Asegurar columnas (por si venías de versiones anteriores)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(stock_items)")}
        if "categoria" not in cols:
            c.execute("ALTER TABLE stock_items ADD COLUMN categoria TEXT")
        if "subtipo" not in cols:
            c.execute("ALTER TABLE stock_items ADD COLUMN subtipo TEXT")

        # 2) Detectar si existe un índice único solo sobre 'pieza' (propio del UNIQUE antiguo)
        def _has_unique_only_pieza() -> bool:
            idx_list = c.execute("PRAGMA index_list(stock_items)").fetchall()
            for idx in idx_list:
                if idx["unique"] != 1:
                    continue
                cols_idx = [r["name"] for r in c.execute(f"PRAGMA index_info('{idx['name']}')").fetchall()]
                # Si el índice único es solo sobre 'pieza', hay que migrar
                if len(cols_idx) == 1 and cols_idx[0] == "pieza":
                    return True
            return False

        if _has_unique_only_pieza():
            # 3) Reconstruir tabla sin UNIQUE en 'pieza'
            c.executescript("""
            BEGIN TRANSACTION;
            CREATE TABLE stock_items_new (
              id         INTEGER PRIMARY KEY AUTOINCREMENT,
              pieza      TEXT    NOT NULL,
              cantidad   INTEGER NOT NULL DEFAULT 0,
              created_at TEXT    DEFAULT (datetime('now')),
              categoria  TEXT,
              subtipo    TEXT
            );
            INSERT INTO stock_items_new(id, pieza, cantidad, created_at, categoria, subtipo)
            SELECT id, pieza, cantidad, created_at, categoria, subtipo FROM stock_items;
            DROP TABLE stock_items;
            ALTER TABLE stock_items_new RENAME TO stock_items;
            COMMIT;
            """)

        # 4) Índices (idempotentes)
        c.execute("CREATE INDEX IF NOT EXISTS idx_stock_items_pieza ON stock_items(pieza)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_stock_items_categoria ON stock_items(categoria)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_stock_items_subtipo ON stock_items(subtipo)")

        # 5) Unicidad compuesta: (pieza, categoria, subtipo)
        #    Permite mismo nombre en distintas categorías/subtipos.
        c.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_stock_pieza_cat_sub
        ON stock_items(pieza, categoria, subtipo)
        """)

# ========= SQL helpers =========
def _select_item_id(c, pieza: str, categoria: str | None, subtipo: str | None):
    """Busca ID por la clave (pieza, categoria, subtipo) tratando NULLs de forma segura."""
    return c.execute(
        """
        SELECT id FROM stock_items
        WHERE pieza = ?
          AND ((categoria IS NULL AND ? IS NULL) OR categoria = ?)
          AND ((subtipo   IS NULL AND ? IS NULL)   OR subtipo   = ?)
        """,
        (pieza, categoria, categoria, subtipo, subtipo),
    ).fetchone()

def _add_item(pieza: str, cantidad_inicial: int = 0, categoria: str | None = None, subtipo: str | None = None):
    pieza = (pieza or "").strip()
    if not pieza:
        return
    cant = max(0, int(cantidad_inicial))
    cat = (categoria or "").strip() or None
    sub = (subtipo or "").strip() or None

    with db.get_conn() as c:
        # Si ya existe ese EXACTO (pieza, categoria, subtipo), solo actualizamos cantidad/meta.
        row = _select_item_id(c, pieza, cat, sub)
        if row:
            iid = int(row["id"])
            c.execute(
                "UPDATE stock_items SET cantidad=?, categoria=?, subtipo=? WHERE id=?",
                (cant, cat, sub, iid),
            )
            return

        # Si no existe, lo insertamos (la unicidad compuesta evita duplicados exactos).
        try:
            c.execute(
                "INSERT INTO stock_items(pieza, cantidad, categoria, subtipo) VALUES (?, ?, ?, ?)",
                (pieza, cant, cat, sub),
            )
        except sqlite3.IntegrityError:
            # Por si hay condición de carrera, caemos al update
            row = _select_item_id(c, pieza, cat, sub)
            if row:
                iid = int(row["id"])
                c.execute(
                    "UPDATE stock_items SET cantidad=?, categoria=?, subtipo=? WHERE id=?",
                    (cant, cat, sub, iid),
                )

def _delete_item(item_id: int):
    with db.get_conn() as c:
        c.execute("DELETE FROM stock_items WHERE id=?", (int(item_id),))

def _update_item_meta(item_id: int, *, nombre: str | None, categoria: str | None, subtipo: str | None) -> tuple[bool, str | None]:
    nom = (nombre or "").strip() if nombre is not None else None
    cat = (categoria or "").strip() if categoria is not None else None
    sub = (subtipo or "").strip() if subtipo is not None else None

    sets, args = [], []
    if nom is not None:
        if not nom:
            return False, "El nombre no puede estar vacío."
        sets.append("pieza=?")
        args.append(nom)
    if cat is not None:
        sets.append("categoria=?")
        args.append(cat if cat else None)
    if sub is not None:
        sets.append("subtipo=?")
        args.append(sub if sub else None)

    if not sets:
        return True, None

    q = f"UPDATE stock_items SET {', '.join(sets)} WHERE id=?"
    args.append(int(item_id))

    try:
        with db.get_conn() as c:
            c.execute(q, tuple(args))
        return True, None
    except sqlite3.IntegrityError:
        return False, "Ya existe un ítem con ese mismo nombre, categoría y subtipo."

def _get_items(search: str | None = None, order_by: str = "pieza", order_dir: str = "ASC",
               categoria: str | None = None, subtipos_filter: list[str] | None = None):
    """
    Trae items con filtros.
    - subtipos_filter puede incluir '__SIN__' para NULL.
    """
    q = "SELECT id, pieza, cantidad, categoria, subtipo FROM stock_items"
    conds, args = [], []

    if search and search.strip():
        conds.append("pieza LIKE ?")
        args.append(f"%{search.strip()}%")

    if categoria:
        conds.append("(categoria = ? OR (categoria IS NULL AND ? = '__NULL__'))")
        args.append(None if categoria == "__SIN__" else categoria)
        args.append("__NULL__" if categoria == "__SIN__" else categoria)

    if subtipos_filter:
        include_null = "__SIN__" in subtipos_filter
        reales = [s for s in subtipos_filter if s != "__SIN__"]
        if reales and include_null:
            placeholders = ",".join(["?"] * len(reales))
            conds.append(f"(subtipo IN ({placeholders}) OR subtipo IS NULL)")
            args.extend(reales)
        elif reales:
            placeholders = ",".join(["?"] * len(reales))
            conds.append(f"subtipo IN ({placeholders})")
            args.extend(reales)
        elif include_null:
            conds.append("subtipo IS NULL")

    if conds:
        q += " WHERE " + " AND ".join(conds)

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

# ========= Helpers de UI =========
def _chips_categorias(items: list[dict]) -> list[tuple[str, int]]:
    """Devuelve lista [(categoria_o_sin, count)] donde '__SIN__' representa sin categoría."""
    counts = defaultdict(int)
    for it in items:
        cat = it.get("categoria") or "__SIN__"
        counts[cat] += 1
    ordered = sorted([(k, v) for k, v in counts.items() if k != "__SIN__"], key=lambda x: x[0].upper())
    if "__SIN__" in counts:
        ordered.append(("__SIN__", counts["__SIN__"]))
    return ordered

def _subtipos_por_categoria(items: list[dict]) -> dict[str, list[tuple[str, int]]]:
    out = defaultdict(lambda: defaultdict(int))
    for it in items:
        cat = it.get("categoria") or "__SIN__"
        sub = it.get("subtipo") or "__SIN__"
        out[cat][sub] += 1
    ordered = {}
    for cat, d in out.items():
        subs_sorted = sorted([(k, v) for k, v in d.items() if k != "__SIN__"], key=lambda x: x[0].upper())
        if "__SIN__" in d:
            subs_sorted.append(("__SIN__", d["__SIN__"]))
        ordered[cat] = subs_sorted
    return ordered

def _card_item(it: dict):
    iid = int(it["id"])
    c1, c2 = st.columns([0.65, 0.35])

    st.markdown(f"**{it['pieza']}**")
    meta = []
    if it.get("categoria"):
        meta.append(f"Cat: {it['categoria']}")
    if it.get("subtipo"):
        meta.append(f"Sub: {it['subtipo']}")
    if meta:
        st.caption(" · ".join(meta))

    with st.form(f"form_delta_{iid}", clear_on_submit=True):
        c1.write(f"Stock: **{int(it['cantidad'])}**")
        delta = c2.number_input("Δ", value=0, step=1, format="%d", label_visibility="collapsed", key=f"delta_{iid}")
        ok = st.form_submit_button("✅", use_container_width=True)
        if ok and int(delta) != 0:
            _add_move(iid, int(delta))
            st.rerun()

    with st.expander("Editar"):
        with st.form(f"form_edit_{iid}", clear_on_submit=True):
            nn = st.text_input("Nombre", value=it["pieza"])
            nc = st.text_input("Categoría", value=it.get("categoria") or "")
            ns = st.text_input("Subtipo", value=it.get("subtipo") or "")
            ccol1, ccol2, ccol3 = st.columns([0.5, 0.25, 0.25])
            save   = ccol1.form_submit_button("💾", use_container_width=True)
            del_btn= ccol2.form_submit_button("🗑", use_container_width=True)
            cancel = ccol3.form_submit_button("✖️", use_container_width=True)
            if save:
                ok, err = _update_item_meta(iid, nombre=nn, categoria=nc, subtipo=ns)
                if ok:
                    st.success("Ítem actualizado.")
                    st.rerun()
                else:
                    st.error(err or "No se pudo actualizar.")
            if del_btn:
                _delete_item(iid)
                st.rerun()

# ========= UI principal =========
def render():
    _ensure_tables_and_migrate()

    st.title("Stock")

    # ---- Alta de pieza ----
    st.subheader("Agregar pieza")
    ca, cb, cc, cd, ce = st.columns([2.4, 1.0, 1.2, 1.4, 0.9])
    pieza_new = ca.text_input("Nombre de pieza", value="", placeholder="Ej: Llavero Escudo Boca")
    cant_new  = cb.number_input("Cantidad inicial", min_value=0, step=1, value=0)
    cat_new   = cc.text_input("Categoría (ej: LLAVEROS, FIGURAS)")
    sub_new   = cd.text_input("Subtipo (ej: Fútbol, Brainrot)")
    if ce.button("➕", use_container_width=True):
        if (pieza_new or "").strip():
            _add_item(pieza_new, int(cant_new), categoria=cat_new, subtipo=sub_new)
            st.success("Pieza cargada.")
            st.rerun()
        else:
            st.warning("Ingresá un nombre de pieza.")

    st.markdown("---")

    # ---- Buscador + Orden + Vista ----
    colb1, colb2, colb3, colb4 = st.columns([1.7, 1.0, 1.0, 1.0])
    search = colb1.text_input("Buscar", value="", placeholder="Filtrar por nombre…")

    orden_label = colb2.selectbox("Ordenar por", ["Nombre (A→Z)", "Cantidad (↓)", "Cantidad (↑)"], index=0)
    if orden_label.startswith("Nombre"):
        order_by, order_dir = "pieza", "ASC"
    elif "↓" in orden_label:
        order_by, order_dir = "cantidad", "DESC"
    else:
        order_by, order_dir = "cantidad", "ASC"

    vista = colb3.selectbox("Vista", options=["Carpetas", "Tabla"], index=0)
    reset = colb4.button("🔄", use_container_width=True)
    if reset:
        st.rerun()

    # ---- Traer items para armar opciones de filtros ----
    items_all = _get_items(search, order_by=order_by, order_dir=order_dir)
    if not items_all:
        st.info("No hay piezas cargadas.")
        return

    # ---- Multiselect Categoría ----
    cat_options_raw = sorted({(it.get("categoria") or "__SIN__") for it in items_all}, key=lambda x: x.upper())
    cat_label_map = {c: ("(sin categoría)" if c == "__SIN__" else c) for c in cat_options_raw}
    cat_options_labels = [cat_label_map[c] for c in cat_options_raw]
    cat_sel_labels = st.multiselect("Categoría", options=cat_options_labels, default=[], placeholder="Elegí una o más categorías…")
    cat_label_to_value = {v: k for k, v in cat_label_map.items()}
    cat_sel_values = [cat_label_to_value[l] for l in cat_sel_labels] if cat_sel_labels else None

    # ---- Multiselect Subtipo ----
    sub_options_raw = sorted({(it.get("subtipo") or "__SIN__") for it in items_all}, key=lambda x: x.upper())
    sub_label_map = {s: ("(sin subtipo)" if s == "__SIN__" else s) for s in sub_options_raw}
    sub_options_labels = [sub_label_map[s] for s in sub_options_raw]
    sub_sel_labels = st.multiselect("Subtipo", options=sub_options_labels, default=[], placeholder="Elegí uno o más (p. ej. Brainrot)…")
    sub_label_to_value = {v: k for k, v in sub_label_map.items()}
    sub_sel_values = [sub_label_to_value[l] for l in sub_sel_labels] if sub_sel_labels else None

    # ---- Aplicar filtros ----
    items = _get_items(search, order_by=order_by, order_dir=order_dir, categoria=None, subtipos_filter=sub_sel_values)
    if cat_sel_values:
        items = [i for i in items if (i.get("categoria") or "__SIN__") in cat_sel_values]

    total_items = len(items)
    total_unidades = sum(int(i["cantidad"]) for i in items)
    st.markdown(f"**Ítems:** {total_items}  ·  **Unidades:** {total_unidades}")

    if vista == "Tabla":
        head = st.columns([2.5, 1.2, 1.2, 1.0, 0.7, 0.7, 0.7])
        head[0].markdown("**Pieza**"); head[1].markdown("**Categoría**"); head[2].markdown("**Subtipo**")
        head[3].markdown("**Stock**"); head[4].markdown("**Δ**"); head[5].markdown("**OK**"); head[6].markdown("**🗑**")

        for it in items:
            iid = int(it["id"])
            with st.form(f"form_tabla_{iid}", clear_on_submit=True):
                c1, c2, c3, c4, c5, c6, c7 = st.columns([2.5, 1.2, 1.2, 1.0, 0.7, 0.7, 0.7])
                nn = c1.text_input("Nombre", value=it["pieza"], label_visibility="collapsed", key=f"n_{iid}")
                nc = c2.text_input("Categoría", value=it.get("categoria") or "", label_visibility="collapsed", key=f"c_{iid}")
                ns = c3.text_input("Subtipo", value=it.get("subtipo") or "", label_visibility="collapsed", key=f"s_{iid}")
                c4.write(f"{int(it['cantidad'])}")
                delta = c5.number_input("Δ", value=0, step=1, format="%d", label_visibility="collapsed", key=f"d_{iid}")
                ok = c6.form_submit_button("✅")
                del_btn = c7.form_submit_button("🗑")
                if ok:
                    okm, err = _update_item_meta(iid, nombre=nn, categoria=nc, subtipo=ns)
                    if not okm: st.error(err or "No se pudo actualizar.")
                    if int(delta) != 0: _add_move(iid, int(delta))
                    if okm or int(delta) != 0: st.rerun()
                if del_btn:
                    _delete_item(iid); st.rerun()
        return

    # ====== Vista Carpetas ======
    st.divider()
    subs_por_cat = _subtipos_por_categoria(items)
    for cat, lista_subs in subs_por_cat.items():
        label_cat = "(sin categoría)" if cat == "__SIN__" else cat
        with st.expander(f"{label_cat}"):
            sub_todos = [s for s, _ in lista_subs]
            selec = st.multiselect("Filtrar subtipos", options=sub_todos, default=sub_todos,
                                   placeholder="Seleccioná subtipos…", key=f"ms_{cat}")
            items_cat = [x for x in items if (x.get("categoria") or "__SIN__") == cat and (x.get("subtipo") or "__SIN__") in selec]
            if not items_cat:
                st.info("No hay ítems para los filtros seleccionados."); continue
            cols_per_row = 4
            for i, it in enumerate(items_cat):
                if i % cols_per_row == 0: row = st.columns(cols_per_row, gap="small")
                with row[i % cols_per_row]:
                    with st.container(border=True): _card_item(it)
