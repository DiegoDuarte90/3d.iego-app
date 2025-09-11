# views/cuentas.py
import streamlit as st
import pandas as pd
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date
from lib import db

# ---------- helpers ----------
def D(x):
    try:
        return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")

def money(x) -> str:
    try:
        v = float(x)
    except Exception:
        v = 0.0
    return f"${v:,.0f}"

# ---------- DDL ----------
DDL_SPLITS = """
CREATE TABLE IF NOT EXISTS payment_splits (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  mov_id       INTEGER NOT NULL,
  part_amount  REAL    NOT NULL,
  cost_divisor INTEGER NOT NULL DEFAULT 1,
  mark_paid    INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT    DEFAULT (datetime('now')),
  updated_at   TEXT    DEFAULT (datetime('now')),
  FOREIGN KEY (mov_id) REFERENCES movimientos(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_payment_splits_mov ON payment_splits(mov_id);
"""

DDL_EXPENSES = """
CREATE TABLE IF NOT EXISTS expenses (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha      TEXT    NOT NULL,   -- YYYY-MM-DD
  concepto   TEXT    NOT NULL,
  monto      REAL    NOT NULL,
  created_at TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_expenses_fecha ON expenses(fecha);
"""

def _ensure_tables():
    with db.get_conn() as c:
        c.executescript(DDL_SPLITS + DDL_EXPENSES)

def _month_bounds(yyyy_mm: str):
    d0 = datetime.strptime(yyyy_mm + "-01", "%Y-%m-%d")
    d1 = (pd.Timestamp(d0).to_period('M').end_time).date()
    return d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d")

def _available_months():
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT DISTINCT substr(fecha,1,7) AS ym FROM movimientos WHERE tipo='pago' ORDER BY ym DESC"
        ).fetchall()
    return [r["ym"] for r in rows] or [date.today().strftime("%Y-%m")]

def _fetch_pagos(ini, fin):
    with db.get_conn() as c:
        rows = c.execute("""
            SELECT m.id, m.rev_id, m.fecha, m.monto, m.medio_pago, r.nombre
            FROM movimientos m
            JOIN revendedores r ON r.id = m.rev_id
            WHERE m.tipo='pago' AND date(m.fecha) BETWEEN ? AND ?
            ORDER BY date(m.fecha) DESC, m.id DESC
        """, (ini, fin)).fetchall()
        return [dict(r) for r in rows]

def _get_splits(mov_id: int):
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT id, mov_id, part_amount, cost_divisor, mark_paid FROM payment_splits WHERE mov_id=? ORDER BY id",
            (mov_id,)
        ).fetchall()
        return [dict(r) for r in rows]

def _ensure_default_split(mov_id: int, monto: float):
    with db.get_conn() as c:
        cnt = c.execute("SELECT COUNT(*) FROM payment_splits WHERE mov_id=?", (mov_id,)).fetchone()[0]
        if cnt == 0:
            c.execute(
                "INSERT INTO payment_splits(mov_id, part_amount, cost_divisor, mark_paid) VALUES (?,?,?,0)",
                (mov_id, float(monto), 1)
            )

def _add_split(mov_id: int, amount: float = 0.0):
    with db.get_conn() as c:
        c.execute(
            "INSERT INTO payment_splits(mov_id, part_amount, cost_divisor, mark_paid) VALUES (?,?,?,0)",
            (mov_id, float(amount), 1)
        )

def _delete_split(split_id: int):
    with db.get_conn() as c:
        c.execute("DELETE FROM payment_splits WHERE id=?", (split_id,))

def _update_split(split_id: int, amount: float, divisor: int, mark: bool):
    with db.get_conn() as c:
        c.execute(
            """UPDATE payment_splits
               SET part_amount=?, cost_divisor=?, mark_paid=?, updated_at=datetime('now')
               WHERE id=?""",
            (float(amount), int(divisor), 1 if mark else 0, int(split_id))
        )

# ---------- Gastos ----------
def _add_expense(fecha: str, concepto: str, monto: float):
    with db.get_conn() as c:
        c.execute("INSERT INTO expenses(fecha, concepto, monto) VALUES (?,?,?)",
                  (fecha, concepto.strip(), float(monto)))

def _del_expense(exp_id: int):
    with db.get_conn() as c:
        c.execute("DELETE FROM expenses WHERE id=?", (int(exp_id),))

def _get_expenses(ini: str, fin: str):
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT id, fecha, concepto, monto FROM expenses WHERE date(fecha) BETWEEN ? AND ? ORDER BY fecha DESC, id DESC",
            (ini, fin)
        ).fetchall()
        return [dict(r) for r in rows]

def _totals_from_splits(ini: str, fin: str):
    """Devuelve (ganancia_bruta, ganancia_media_total, ganancia_media_pendiente)."""
    with db.get_conn() as c:
        rows = c.execute("""
            SELECT s.part_amount AS amt, s.cost_divisor AS div, s.mark_paid AS paid
            FROM payment_splits s
            JOIN movimientos m ON m.id = s.mov_id
            WHERE m.tipo='pago' AND date(m.fecha) BETWEEN ? AND ?
        """, (ini, fin)).fetchall()
    gan_total = D(0)
    gm_total  = D(0)
    gm_pend   = D(0)
    for r in rows:
        amt = D(r["amt"]); div = D(int(r["div"]) if int(r["div"]) else 1)
        gan = amt - (amt / div)
        gm  = gan / D(2)
        gan_total += gan
        gm_total  += gm
        if int(r["paid"]) == 0:
            gm_pend += gm
    return gan_total, gm_total, gm_pend

# ---------- UI ----------
def render():
    _ensure_tables()

    # CSS (compacto)
    st.markdown("""
    <style>
      .block-container{padding-top:.3rem;padding-bottom:.5rem}
      h1{margin:.1rem 0 .4rem!important} h2,h3{margin:.2rem 0 .35rem!important}
      [data-testid="stExpander"]{margin:.25rem 0;border-radius:.5rem;border:1px solid #2a2f3a}
      [data-testid="stExpander"] details>summary{padding:.2rem .45rem;font-size:.9rem}
      div[data-testid="stHorizontalBlock"]{gap:.2rem!important} div[data-testid="column"]{padding:0 .12rem}
      .stNumberInput, .stSelectbox, .stCheckbox, .stTextInput, .stDateInput{margin-bottom:.08rem}
      .stNumberInput input, .stTextInput input{padding:.12rem .35rem;height:24px;font-size:12px}
      div[data-baseweb="select"]>div{min-height:24px} div[data-baseweb="select"] *{font-size:12px}
      [data-testid="stCheckbox"] label{font-size:12px} button[kind]{min-height:24px!important;padding:.08rem .45rem!important;font-size:12px!important}
      .mini{font-size:.85rem;background:#12151c;border:1px solid #272b35;border-radius:.35rem;padding:.15rem .35rem;text-align:center;white-space:nowrap}
      .sep{border-top:1px solid #252a33;margin:.35rem 0}
      .warn{background:#3a3205;border:1px solid #7a650c;padding:.2rem .4rem;border-radius:.35rem;font-size:.8rem}
      .kpicard{background:#0f1117;border:1px solid #2a2f3a;border-radius:.6rem;padding:.4rem .6rem}
      .kpititle{font-size:.72rem;color:#9aa;text-transform:uppercase;letter-spacing:.05em}
      .kpiv{font-size:1rem;font-weight:600}
      .muted{color:#9aa;font-size:.8rem}
      .pill{display:inline-block;border:1px solid #2a2f3a;border-radius:.6rem;padding:.15rem .4rem}
      .lbl{font-size:.65rem;color:#9aa;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.1rem}
    </style>
    """, unsafe_allow_html=True)

    st.title("Cuentas")

    meses = _available_months()
    mes_sel = st.selectbox("Mes", meses, index=0)
    ini, fin = _month_bounds(mes_sel)

    # ---- Resumen del mes (ventas + gastos) ----
    gan_total, gm_total, gm_pend = _totals_from_splits(ini, fin)
    expenses = _get_expenses(ini, fin)
    gastos_total = D(sum(float(e["monto"]) for e in expenses))
    gan_neta = gan_total - gastos_total

    # Individual (pendiente) = GM no pagado - gastos/2 (compartidos)
    individual_pend = gm_pend - (gastos_total / D(2))
    if individual_pend < D(0):
        individual_pend = D(0)

    cA, cB, cC, cD = st.columns([1.1, 1.1, 1.0, 1.1])
    with cA:
        st.markdown("<div class='kpicard'><div class='kpititle'>Ganancia individual (pendiente)</div>"
                    f"<div class='kpiv'>{money(individual_pend)}</div></div>", unsafe_allow_html=True)

    with cB:
        st.markdown("<div class='kpicard'><div class='kpititle'>Ganancia bruta</div>"
                    f"<div class='kpiv'>{money(gan_total)}</div></div>", unsafe_allow_html=True)
    with cC:
        st.markdown("<div class='kpicard'><div class='kpititle'>Gastos del mes</div>"
                    f"<div class='kpiv'>{money(gastos_total)}</div></div>", unsafe_allow_html=True)
    with cD:
        st.markdown("<div class='kpicard'><div class='kpititle'>Ganancia neta</div>"
                    f"<div class='kpiv'>{money(gan_neta)}</div></div>", unsafe_allow_html=True)

    # ---- Carga y listado de GASTOS (del mes) ----
    with st.expander("Gastos del mes", expanded=False):
        g1, g2, g3, g4 = st.columns([.8, 2.0, .9, .7])
        g1.caption("FECHA"); g2.caption("CONCEPTO"); g3.caption("MONTO")
        fecha_g = g1.date_input("Fecha", value=date.today(), format="YYYY-MM-DD", label_visibility="collapsed")
        concepto_g = g2.text_input("Concepto", value="", placeholder="Detalle del gasto", label_visibility="collapsed")
        monto_g = g3.number_input("Monto", min_value=0.0, step=100.0, value=0.0, label_visibility="collapsed")
        if g4.button("➕ Agregar", key="add_exp"):
            if concepto_g and float(monto_g) > 0:
                _add_expense(fecha_g.strftime("%Y-%m-%d"), concepto_g, float(monto_g))
                st.rerun()

        if expenses:
            st.markdown("<span class='muted'>Listado</span>", unsafe_allow_html=True)
            for e in expenses:
                c1, c2, c3, c4 = st.columns([.9, 2.2, .9, .6])
                c1.markdown(f"<div class='pill'>{e['fecha']}</div>", unsafe_allow_html=True)
                c2.write(e["concepto"])
                c3.markdown(f"<div class='mini'>{money(e['monto'])}</div>", unsafe_allow_html=True)
                if c4.button("🗑", key=f"del_exp_{e['id']}"):
                    _del_expense(e["id"]); st.rerun()
        else:
            st.caption("Sin gastos cargados en este mes.")

    # ---- Pagos del mes ----
    pagos = _fetch_pagos(ini, fin)
    if not pagos:
        st.info("Sin pagos en este mes.")
        return

    st.subheader("Pagos del mes")

    for idx, p in enumerate(pagos, start=1):
        pid   = int(p["id"])
        monto = D(p["monto"])
        st.markdown(f"**Pago #{idx}** — {p['fecha']} — {p['nombre']} — {money(monto)} — {p['medio_pago'] or '—'}")

        _ensure_default_split(pid, float(monto))
        partes = _get_splits(pid)

        with st.expander("Partes / Ajustes", expanded=True):
            # FILA ULTRA COMPACTA POR PARTE (7 columnas) + etiquetas encima de cada cifra
            for s in partes:
                sid = int(s["id"])
                c1, c2, c3, c4, c5, c6, c7 = st.columns([1.05,.7,.7,.7,.7,.5,.5])

                c1.markdown("<div class='lbl'>MONTO</div>", unsafe_allow_html=True)
                c2.markdown("<div class='lbl'>DIV</div>", unsafe_allow_html=True)
                c3.markdown("<div class='lbl'>COSTO</div>", unsafe_allow_html=True)
                c4.markdown("<div class='lbl'>GAN</div>", unsafe_allow_html=True)
                c5.markdown("<div class='lbl'>GM</div>", unsafe_allow_html=True)
                c6.markdown("<div class='lbl'>PAGO</div>", unsafe_allow_html=True)
                c7.markdown("<div class='lbl'>ACC.</div>", unsafe_allow_html=True)

                amt = c1.number_input("Monto", min_value=0.0, step=100.0,
                                      value=float(s["part_amount"]), key=f"pa_{sid}", label_visibility="collapsed")
                div = c2.selectbox("Div", list(range(1,11)),
                                   index=(int(s["cost_divisor"])-1 if 1<=int(s["cost_divisor"])<=10 else 0),
                                   key=f"dv_{sid}", label_visibility="collapsed")

                costo = D(amt) / D(div or 1)
                gan   = D(amt) - costo
                gm    = gan / D(2)

                c3.markdown(f"<div class='mini'>{money(costo)}</div>", unsafe_allow_html=True)
                c4.markdown(f"<div class='mini'>{money(gan)}</div>",   unsafe_allow_html=True)
                c5.markdown(f"<div class='mini'>{money(gm)}</div>",    unsafe_allow_html=True)

                c6.checkbox("Pago", value=bool(s["mark_paid"]), key=f"mk_{sid}", label_visibility="collapsed")
                if c7.button("🗑", key=f"del_{sid}"):
                    _delete_split(sid); st.rerun()

            # Suma visible + warning
            sum_ui = 0.0
            for s in partes:
                sid = int(s["id"])
                sum_ui += float(st.session_state.get(f"pa_{sid}", s["part_amount"]))
            restante = float(monto) - sum_ui
            if abs(restante) > 0.01:
                st.markdown(
                    f"<div class='warn'>⚠️ Suma {money(sum_ui)} ≠ Pago {money(monto)} (resta {money(restante)}).</div>",
                    unsafe_allow_html=True
                )
            else:
                st.caption(f"✔️ Suma OK ({money(sum_ui)}).")

            # Acciones
            b1, b2 = st.columns([.9, .9])
            if b1.button("💾 Guardar", key=f"save_{pid}"):
                for s in partes:
                    sid = int(s["id"])
                    amt = float(st.session_state.get(f"pa_{sid}", s["part_amount"]))
                    div = int(st.session_state.get(f"dv_{sid}", s["cost_divisor"]))
                    mk  = bool(st.session_state.get(f"mk_{sid}", s["mark_paid"]))
                    _update_split(sid, amt, div, mk)
                for s in partes:
                    sid = int(s["id"])
                    st.session_state.pop(f"pa_{sid}", None)
                    st.session_state.pop(f"dv_{sid}", None)
                    st.session_state.pop(f"mk_{sid}", None)
                st.rerun()

            if b2.button("➕ Parte", key=f"add_{pid}"):
                _add_split(pid, max(0.0, float(monto) - sum_ui))
                st.rerun()

        st.markdown("<div class='sep'></div>", unsafe_allow_html=True)

    # ---- Totales del mes (netos) ----
    st.subheader("Totales del mes")
    c1, c2, c3 = st.columns(3)
    c1.write(f"**Ganancia bruta:** {money(gan_total)}")
    c2.writ
