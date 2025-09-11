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
def _ensure_table():
    with db.get_conn() as c:
        c.executescript(DDL_SPLITS)

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

# ---------- UI ----------
def render():
    _ensure_table()

    # CSS ULTRA COMPACTO
    st.markdown("""
    <style>
      .block-container{padding-top:.3rem;padding-bottom:.5rem}
      h1{margin:.1rem 0 .4rem!important}
      h2,h3{margin:.2rem 0 .35rem!important}
      [data-testid="stExpander"]{margin:.25rem 0;border-radius:.5rem;border:1px solid #2a2f3a}
      [data-testid="stExpander"] details>summary{padding:.2rem .45rem;font-size:.9rem}
      div[data-testid="stHorizontalBlock"]{gap:.2rem!important}
      div[data-testid="column"]{padding:0 .12rem}
      .stNumberInput, .stSelectbox, .stCheckbox{margin-bottom:.08rem}
      .stNumberInput input{padding:.12rem .35rem;height:24px;font-size:12px}
      div[data-baseweb="select"]>div{min-height:24px}
      div[data-baseweb="select"] *{font-size:12px}
      [data-testid="stCheckbox"] label{font-size:12px}
      button[kind]{min-height:24px!important;padding:.08rem .45rem!important;font-size:12px!important}
      .mini{font-size:.85rem;background:#12151c;border:1px solid #272b35;border-radius:.35rem;
            padding:.15rem .35rem;text-align:center;white-space:nowrap}
      .head{font-size:.7rem;color:#9aa;letter-spacing:.04em;text-transform:uppercase;margin:.1rem 0 .15rem}
      .sep{border-top:1px solid #252a33;margin:.35rem 0}
      .warn{background:#3a3205;border:1px solid #7a650c;padding:.2rem .4rem;border-radius:.35rem;font-size:.8rem}
    </style>
    """, unsafe_allow_html=True)

    st.title("Cuentas")

    meses = _available_months()
    mes_sel = st.selectbox("Mes", meses, index=0)
    ini, fin = _month_bounds(mes_sel)

    pagos = _fetch_pagos(ini, fin)
    if not pagos:
        st.info("Sin pagos en este mes.")
        return

    st.subheader("Pagos del mes")
    total_gan = D(0); total_gm = D(0)

    for idx, p in enumerate(pagos, start=1):
        pid   = int(p["id"])
        monto = D(p["monto"])
        st.markdown(f"**Pago #{idx}** — {p['fecha']} — {p['nombre']} — {money(monto)} — {p['medio_pago'] or '—'}")

        _ensure_default_split(pid, float(monto))
        partes = _get_splits(pid)

        with st.expander("Partes / Ajustes", expanded=True):
            st.markdown("<div class='head'>Monto · Div · Costo · Gan · GM · Pago · Acc.</div>", unsafe_allow_html=True)

            # FILA ULTRA COMPACTA POR PARTE (7 columnas)
            for s in partes:
                sid = int(s["id"])
                c1, c2, c3, c4, c5, c6, c7 = st.columns([1.05,.7,.7,.7,.7,.5,.5])

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

                total_gan += gan; total_gm += gm

            # Suma visible + warning MINI
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

            # Barra compacta de acciones por pago (SIN autocuadrar)
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

    # Totales súper compactos
    st.subheader("Totales del mes")
    c1, c2 = st.columns(2)
    c1.write(f"**Ganancia:** {money(total_gan)}")
    c2.write(f"**Ganancia media:** {money(total_gm)}")

    # Totales por método (opcional)
    with db.get_conn() as c:
        df = pd.read_sql_query(
            """
            SELECT s.part_amount,
                   (s.part_amount / NULLIF(s.cost_divisor,0)) AS costo,
                   (s.part_amount - (s.part_amount/NULLIF(s.cost_divisor,0))) AS ganancia,
                   m.medio_pago
            FROM payment_splits s
            JOIN movimientos m ON m.id = s.mov_id
            WHERE m.tipo='pago' AND date(m.fecha) BETWEEN ? AND ?
            """,
            c, params=[ini, fin]
        )
    if not df.empty:
        df["ganancia_media"] = df["ganancia"] / 2.0
        st.caption("Por método")
        st.dataframe(
            df.groupby(df["medio_pago"].fillna("—"))[
                ["part_amount","costo","ganancia","ganancia_media"]
            ].sum().round(0).rename(columns={
                "part_amount":"MONTO","costo":"COSTO","ganancia":"GANANCIA","ganancia_media":"GAN. MEDIA"
            }),
            width="stretch"
        )
