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
  mark_paid    INTEGER NOT NULL DEFAULT 0, -- compatibilidad; no se usa en UI
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

# Libro de pagos a Romina
DDL_PAYOUTS = """
CREATE TABLE IF NOT EXISTS partner_payouts (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha      TEXT    NOT NULL,   -- YYYY-MM-DD
  monto      REAL    NOT NULL,
  nota       TEXT,
  created_at TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_partner_payouts_fecha ON partner_payouts(fecha);
"""

def _ensure_tables():
    with db.get_conn() as c:
        c.executescript(DDL_SPLITS + DDL_EXPENSES + DDL_PAYOUTS)

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

def _update_split(split_id: int, amount: float, divisor: int):
    with db.get_conn() as c:
        c.execute(
            """UPDATE payment_splits
               SET part_amount=?, cost_divisor=?, updated_at=datetime('now')
               WHERE id=?""",
            (float(amount), int(divisor), int(split_id))
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

# ---------- Pagos a Romina ----------
def _add_payout(fecha: str, monto: float, nota: str | None):
    with db.get_conn() as c:
        c.execute("INSERT INTO partner_payouts(fecha, monto, nota) VALUES (?,?,?)",
                  (fecha, float(monto), (nota or "").strip()))

def _update_payout(pid: int, fecha: str, monto: float, nota: str | None):
    with db.get_conn() as c:
        c.execute("UPDATE partner_payouts SET fecha=?, monto=?, nota=? WHERE id=?",
                  (fecha, float(monto), (nota or "").strip(), int(pid)))

def _del_payout(pid: int):
    with db.get_conn() as c:
        c.execute("DELETE FROM partner_payouts WHERE id=?", (int(pid),))

def _get_payouts(ini: str, fin: str):
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT id, fecha, monto, nota FROM partner_payouts WHERE date(fecha) BETWEEN ? AND ? ORDER BY fecha DESC, id DESC",
            (ini, fin)
        ).fetchall()
        return [dict(r) for r in rows]

# ---------- Totales desde splits ----------
def _totals_from_splits(ini: str, fin: str):
    """Devuelve (ganancia_bruta, ganancia_media_total)."""
    with db.get_conn() as c:
        rows = c.execute("""
            SELECT s.part_amount AS amt, s.cost_divisor AS div
            FROM payment_splits s
            JOIN movimientos m ON m.id = s.mov_id
            WHERE m.tipo='pago' AND date(m.fecha) BETWEEN ? AND ?
        """, (ini, fin)).fetchall()
    gan_total = D(0)
    gm_total  = D(0)
    for r in rows:
        amt = D(r["amt"]); div = D(int(r["div"]) if int(r["div"]) else 1)
        costo = amt / div
        gan   = amt - costo
        gm    = gan / D(2)
        gan_total += gan
        gm_total  += gm
    return gan_total, gm_total

# ---------- UI ----------
def render():
    _ensure_tables()

    # CSS compacto
    st.markdown("""
    <style>
      .block-container{padding-top:.3rem;padding-bottom:.5rem}
      h1{margin:.1rem 0 .4rem!important} h2,h3{margin:.2rem 0 .35rem!important}
      [data-testid="stExpander"]{margin:.25rem 0;border-radius:.5rem;border:1px solid #2a2f3a}
      div[data-testid="stHorizontalBlock"]{gap:.2rem!important} div[data-testid="column"]{padding:0 .12rem}
      .stNumberInput input, .stTextInput input{padding:.12rem .35rem;height:24px;font-size:12px}
      button[kind]{min-height:24px!important;padding:.08rem .45rem!important;font-size:12px!important}
      .mini{font-size:.85rem;background:#12151c;border:1px solid #272b35;border-radius:.35rem;padding:.15rem .35rem;text-align:center;white-space:nowrap}
      .sep{border-top:1px solid #252a33;margin:.35rem 0}
      .warn{background:#3a3205;border:1px solid #7a650c;padding:.2rem .4rem;border-radius:.35rem;font-size:.8rem}
      .kpicard{background:#0f1117;border:1px solid #2a2f3a;border-radius:.6rem;padding:.5rem .6rem}
      .kpititle{font-size:.72rem;color:#9aa;text-transform:uppercase;letter-spacing:.05em}
      .kpiv{font-size:1rem;font-weight:600}
      .muted{color:#9aa;font-size:.8rem}
      .pill{display:inline-block;border:1px solid #2a2f3a;border-radius:.6rem;padding:.15rem .4rem}
      .lbl{font-size:.65rem;color:#9aa;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.1rem}
      .neg{color:#ff4d4f}
      #overlay{ position:fixed; z-index:10050; inset:0; background:rgba(0,0,0,.55); }
      #modal{
        position:fixed; z-index:10060; left:50%; top:50%;
        transform:translate(-50%,-50%); width:min(820px, 94vw); max-height:80vh; overflow:auto;
        background:#11151a; border:1px solid rgba(255,255,255,.15); border-radius:12px; padding:16px;
      }
    </style>
    """, unsafe_allow_html=True)

    st.title("Cuentas")

    # Estado UI
    ss = st.session_state
    ss.setdefault("show_payout_modal", False)
    ss.setdefault("payout_modal_armed", False)  # ← clave: solo se arma con la lupa
    ss.setdefault("payout_edit_id", None)
    ss.setdefault("_payout_edit_fecha", None)
    ss.setdefault("_payout_edit_monto", None)
    ss.setdefault("_payout_edit_nota", "")

    meses = _available_months()
    mes_sel = st.selectbox("Mes", meses, index=0)
    ini, fin = _month_bounds(mes_sel)

    # ---- Totales (ventas + gastos) ----
    gan_total, gm_total = _totals_from_splits(ini, fin)
    expenses = _get_expenses(ini, fin)
    gastos_total = D(sum(float(e["monto"]) for e in expenses))

    # Pagos a Romina del mes
    payouts = _get_payouts(ini, fin)
    payouts_total = D(sum(float(p["monto"]) for p in payouts))

    # KPI: Ganancia individual (mes)
    gan_individual = gm_total - (gastos_total / D(2))
    # KPI: Pago a Romina (mes)
    pago_a_romina = gan_individual - payouts_total

    # ---- KPIs ----
    cA, cB, cC, cD = st.columns([1.35, 1.25, 1.0, 1.1])

    with cA:
        color_cls = "kpiv neg" if pago_a_romina > D(0) else "kpiv"
        st.markdown(
            "<div class='kpicard'>"
            "<div class='kpititle'>Pago a Romina (mes)</div>"
            f"<div class='{color_cls}'>{money(pago_a_romina)}</div>"
            "<div class='muted'>= Ganancia individual − pagos registrados</div>",
            unsafe_allow_html=True
        )
        # Solo arma y abre el modal al click
        if st.button("🔎", key="btn_open_payout_dialog"):
            ss.show_payout_modal = True
            ss.payout_modal_armed = True   # ← se arma acá
            ss.payout_edit_id = None
            st.rerun()

    with cB:
        color_cls = "kpiv neg" if gan_individual < D(0) else "kpiv"
        st.markdown(
            "<div class='kpicard'>"
            "<div class='kpititle'>Ganancia individual (mes)</div>"
            f"<div class='{color_cls}'>{money(gan_individual)}</div>"
            "<div class='muted'>= GM mes − gastos/2</div>"
            "</div>",
            unsafe_allow_html=True
        )

    with cC:
        st.markdown(
            "<div class='kpicard'><div class='kpititle'>Gastos del mes</div>"
            f"<div class='kpiv'>{money(gastos_total)}</div></div>",
            unsafe_allow_html=True
        )

    with cD:
        gan_neta_mes = gan_total - gastos_total
        st.markdown(
            "<div class='kpicard'><div class='kpititle'>Ganancia neta (global)</div>"
            f"<div class='kpiv'>{money(gan_neta_mes)}</div></div>",
            unsafe_allow_html=True
        )

    # ---- GASTOS del mes ----
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

    # ---- Pagos del mes (ventas) ----
    pagos = _fetch_pagos(ini, fin)
    if not pagos:
        st.info("Sin pagos en este mes.")
        _maybe_open_payout_dialog(ini, fin)  # por si quedó armado y abierto
        return

    st.subheader("Pagos del mes")
    for idx, p in enumerate(pagos, start=1):
        pid   = int(p["id"])
        monto = D(p["monto"])
        st.markdown(f"**Pago #{idx}** — {p['fecha']} — {p['nombre']} — {money(monto)} — {p['medio_pago'] or '—'}")

        _ensure_default_split(pid, float(monto))
        partes = _get_splits(pid)

        with st.expander("Partes / Ajustes", expanded=True):
            for s in partes:
                sid = int(s["id"])
                c1, c2, c3, c4, c5, c6 = st.columns([1.05,.7,.7,.7,.6,.6])

                c1.markdown("<div class='lbl'>MONTO</div>", unsafe_allow_html=True)
                c2.markdown("<div class='lbl'>DIV</div>", unsafe_allow_html=True)
                c3.markdown("<div class='lbl'>COSTO</div>", unsafe_allow_html=True)
                c4.markdown("<div class='lbl'>GAN</div>", unsafe_allow_html=True)
                c5.markdown("<div class='lbl'>GM</div>", unsafe_allow_html=True)
                c6.markdown("<div class='lbl'>ACC.</div>", unsafe_allow_html=True)

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

                if c6.button("🗑", key=f"del_{sid}"):
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
                    _update_split(sid, amt, div)
                for s in partes:
                    sid = int(s["id"])
                    st.session_state.pop(f"pa_{sid}", None)
                    st.session_state.pop(f"dv_{sid}", None)
                st.rerun()

            if b2.button("➕ Parte", key=f"add_{pid}"):
                _add_split(pid, max(0.0, float(monto) - sum_ui))
                st.rerun()

        st.markdown("<div class='sep'></div>", unsafe_allow_html=True)

    # ---- Totales del mes (resumen textual) ----
    st.subheader("Totales del mes")
    c1, c2, c3, c4 = st.columns([1.1, 1.1, 1.1, 1.1])
    c1.write(f"**Ganancia bruta (global):** {money(gan_total)}")
    c2.write(f"**Gastos del mes (global):** {money(gastos_total)}")
    c3.write(f"**Ganancia individual (mes):** {money(gan_individual)}")
    c4.write(f"**Pago a Romina (mes):** {money(pago_a_romina)}")

    # Render del popup SOLO si fue armado por la lupa
    _maybe_open_payout_dialog(ini, fin)


# ====================== Popup "lupa" pagos Romina ======================

def _maybe_open_payout_dialog(ini: str, fin: str):
    ss = st.session_state
    # ← condición estricta: solo renderiza si fue "armado" explícitamente por el botón
    if not (ss.get("show_payout_modal") and ss.get("payout_modal_armed")):
        return

    try:
        dialog = getattr(st, "dialog")
    except AttributeError:
        dialog = None

    if dialog:
        @dialog("Pagos a Romina")
        def _dlg():
            _render_payout_dialog_content(ini, fin)
        _dlg()
    else:
        st.markdown("<div id='overlay'></div><div id='modal'><h4>Pagos a Romina</h4></div>", unsafe_allow_html=True)
        _render_payout_dialog_content(ini, fin)


def _render_payout_dialog_content(ini: str, fin: str):
    ss = st.session_state

    # Form alta/edición — Monto (foco inicial), Nota, y Fecha al final (default hoy)
    with st.form("payout_form", clear_on_submit=False):
        monto_val = st.number_input("Monto", min_value=0.0, step=100.0,
                                    value=(ss.get("_payout_edit_monto", 0.0) if ss.get("payout_edit_id") else 0.0))
        nota_val  = st.text_input("Nota (opcional)", value=(ss.get("_payout_edit_nota", "") if ss.get("payout_edit_id") else ""))
        default_fecha = (ss.get("_payout_edit_fecha") or date.today())
        fecha_val = st.date_input("Fecha", value=default_fecha, format="YYYY-MM-DD")  # no se abre solo

        bcol1, bcol2, bcol3 = st.columns([.6, .2, .2])
        ok = bcol1.form_submit_button("Guardar")
        cancel = bcol2.form_submit_button("Cancelar")
        if ok and float(monto_val) > 0:
            if ss.get("payout_edit_id") is None:
                _add_payout(fecha_val.strftime("%Y-%m-%d"), float(monto_val), nota_val)
            else:
                _update_payout(ss["payout_edit_id"], fecha_val.strftime("%Y-%m-%d"), float(monto_val), nota_val)
            # limpiar estado y cerrar
            _close_payout_modal()
            st.rerun()
        if cancel:
            _close_payout_modal()
            st.rerun()

    st.markdown("---")
    # Listado del mes (SOLO dentro del popup)
    payouts = _get_payouts(ini, fin)
    if not payouts:
        st.info("Sin pagos registrados en este mes.")
    else:
        hdr = st.columns([.9, .9, 2.0, .7, .7])
        hdr[0].markdown("**Fecha**"); hdr[1].markdown("**Monto**"); hdr[2].markdown("**Nota**")
        hdr[3].markdown("**Editar**"); hdr[4].markdown("**Borrar**")
        for e in payouts:
            c1, c2, c3, c4, c5 = st.columns([.9, .9, 2.0, .7, .7])
            c1.write(e["fecha"])
            c2.write(money(e["monto"]))
            c3.write(e.get("nota") or "—")
            if c4.button("✏️", key=f"payout_edit_{e['id']}"):
                ss.payout_edit_id = e["id"]
                ss._payout_edit_fecha = datetime.strptime(e["fecha"], "%Y-%m-%d").date()
                ss._payout_edit_monto = float(e["monto"])
                ss._payout_edit_nota  = e.get("nota") or ""
                st.rerun()
            if c5.button("🗑", key=f"payout_del_{e['id']}"):
                _del_payout(e["id"])
                st.rerun()

    # Cerrar (cuando no hay st.dialog, botón Cerrar)
    try:
        getattr(st, "dialog")
    except AttributeError:
        if st.button("Cerrar"):
            _close_payout_modal()
            st.rerun()


def _close_payout_modal():
    """Resetea todas las flags del modal para que no vuelva a abrirse solo."""
    ss = st.session_state
    ss.show_payout_modal = False
    ss.payout_modal_armed = False
    ss.payout_edit_id = None
    ss._payout_edit_fecha = None
    ss._payout_edit_monto = None
    ss._payout_edit_nota  = ""
