# views/entregas.py
import streamlit as st
import pandas as pd
from datetime import date, datetime
from pathlib import Path
import re
import base64
from glob import glob

from lib import db
from lib.pdfgen import build_entrega_pdf  # PDF directo con ReportLab

DEFAULT_OPT = "— Elegir revendedor —"


def render():
    # Ancla para el botón "↑ Subir"
    st.markdown('<a id="top"></a>', unsafe_allow_html=True)

    st.title("Entregas")

    ss = st.session_state
    ss.setdefault("ent_items", [])
    ss.setdefault("particular_open", False)
    ss.setdefault("particular_nombre", "")
    ss.setdefault("ent_fecha", date.today())
    ss.setdefault("ent_pieza", "")
    ss.setdefault("ent_cantidad", 1)
    ss.setdefault("ent_precio", 0.0)

    ss.setdefault("ent_cliente", {"tipo": None, "rev_id": None, "nombre": ""})
    ss.setdefault("sel_rev", DEFAULT_OPT)
    ss.setdefault("reset_sel_rev", False)

    ss["show_entrega_modal"] = ss.get("show_entrega_modal", False) and bool(ss.get("modal_entrega_id"))
    ss.setdefault("modal_entrega_id", None)
    ss.setdefault("modal_entrega_nro", None)

    # ---------------- Selección cliente ----------------
    st.subheader("Seleccione cliente")
    c1, c2 = st.columns([3, 1])

    if ss.reset_sel_rev:
        ss.sel_rev = DEFAULT_OPT
        ss.reset_sel_rev = False

    with c1:
        revs = db.get_revendedores(None)
        opciones = [DEFAULT_OPT] + [f"{r['id']} - {r['nombre']}" for r in revs]
        sel = st.selectbox("Revendedor", opciones, key="sel_rev", label_visibility="collapsed")
        if sel != DEFAULT_OPT:
            try:
                rid = int(sel.split(" - ")[0])
                rname = sel.split(" - ", 1)[1]
                ss.ent_cliente = {"tipo": "rev", "rev_id": rid, "nombre": rname}
                ss.particular_nombre = ""
            except Exception:
                pass

    with c2:
        if st.button("Particular", use_container_width=True):
            ss.particular_open = True

    if ss.particular_open:
        with st.form("form_particular", clear_on_submit=False):
            st.write("Cliente Particular")
            ss.particular_nombre = st.text_input("Nombre del cliente", value=ss.particular_nombre)
            colp1, colp2 = st.columns([1, 1])
            ok = colp1.form_submit_button("Usar este cliente")
            cancel = colp2.form_submit_button("Cancelar")
            if ok:
                nombre = ss.particular_nombre.strip()
                if not nombre:
                    st.warning("Ingresá un nombre válido.")
                else:
                    ss.ent_cliente = {"tipo": "part", "rev_id": None, "nombre": nombre}
                    ss.particular_open = False
                    ss.reset_sel_rev = True
                    st.success(f"Cliente particular seleccionado: {nombre}")
                    st.rerun()
            if cancel:
                ss.particular_open = False
                ss.particular_nombre = ""
                st.rerun()

    st.markdown("")
    cli = ss.ent_cliente
    if cli["tipo"] == "rev":
        st.info(f"Cliente seleccionado: **Revendedor {cli['nombre']}** (ID {cli['rev_id']}).")
    elif cli["tipo"] == "part":
        st.info(f"Cliente seleccionado: **Particular {cli['nombre']}**.")
    else:
        st.warning("Elegí un **revendedor** o cargá un **particular** para continuar.")

    # ---------------- Agregar pieza ----------------
    st.markdown("---")
    st.subheader("Agregar pieza")

    cA, cB, cC, cD, cE = st.columns([1.1, 3, 1.1, 1.1, 1.1])
    with cA:
        ss.ent_fecha = st.date_input("Fecha", value=ss.ent_fecha, key="inp_fecha")
    with cB:
        ss.ent_pieza = st.text_input("Pieza / Descripción", value=ss.ent_pieza, key="inp_pieza")
    with cC:
        ss.ent_cantidad = st.number_input("Cantidad", min_value=1, step=1, value=ss.ent_cantidad, key="inp_cant")
    with cD:
        ss.ent_precio = st.number_input("Precio x pieza", min_value=0.0, step=100.0,
                                        value=float(ss.ent_precio), format="%.2f", key="inp_precio")
    with cE:
        total_vivo = float(ss.ent_cantidad) * float(ss.ent_precio)
        st.text_input("Total", value=f"{total_vivo:,.2f}", disabled=True)

    if st.button("Agregar pieza", type="primary"):
        if not ss.ent_pieza.strip():
            st.warning("Ingresá una descripción.")
        else:
            ss.ent_items.append({
                "pieza": ss.ent_pieza.strip(),
                "cantidad": int(ss.ent_cantidad),
                "precio": float(ss.ent_precio),
                "total": float(total_vivo),
                "fecha": ss.ent_fecha,
            })
            ss.ent_pieza = ""
            ss.ent_cantidad = 1
            ss.ent_precio = 0.0
            ss.show_entrega_modal = False
            ss.modal_entrega_id = None
            ss.modal_entrega_nro = None
            st.rerun()

    # -------------- Piezas agregadas --------------
    if ss.ent_items:
        st.markdown("#### Piezas agregadas")
        cols = st.columns([3, 1.2, 1.2, 1.2, 0.8])
        cols[0].markdown("**Pieza**")
        cols[1].markdown("**Cantidad**")
        cols[2].markdown("**Precio**")
        cols[3].markdown("**Total**")
        cols[4].markdown("**Borrar**")

        suma = 0.0
        for i, it in enumerate(ss.ent_items):
            c1, c2, c3, c4, c5 = st.columns([3, 1.2, 1.2, 1.2, 0.8])
            c1.write(it["pieza"])

            new_qty = c2.number_input(" ", min_value=1, step=1, value=int(it["cantidad"]),
                                      key=f"qty_{i}", label_visibility="collapsed")
            if new_qty != it["cantidad"]:
                it["cantidad"] = int(new_qty)
                it["total"] = float(it["cantidad"]) * float(it["precio"])
                st.rerun()

            c3.write(f"{it['precio']:,.2f}")
            c4.write(f"{it['total']:,.2f}")
            suma += it["total"]

            if c5.button("✖", key=f"del_item_{i}"):
                ss.ent_items.pop(i)
                st.rerun()

        st.markdown(f"### Total: **${suma:,.2f}**")

        if st.button("Guardar entrega"):
            if cli["tipo"] not in ("rev", "part"):
                st.warning("Seleccioná un revendedor o cargá un particular.")
            else:
                fecha_iso = (ss.ent_items[-1]["fecha"]).strftime("%Y-%m-%d")
                items = [{k: it[k] for k in ("pieza","cantidad","precio","total")} for it in ss.ent_items]
                try:
                    info = db.save_entrega(
                        rev_id=(cli["rev_id"] if cli["tipo"] == "rev" else None),
                        cliente=(cli["nombre"] if cli["tipo"] == "part" else None),
                        fecha=fecha_iso,
                        items=items,
                    )
                    pdf_bytes, saved_path, filename = _build_pdf_for_entrega(
                        entrega_id=info["entrega_id"],
                        entrega_nro=info["entrega_nro"],
                        cliente=("Particular " + cli["nombre"] if cli["tipo"] == "part" else cli["nombre"]),
                        fecha_iso=fecha_iso
                    )
                    st.success(f"Entrega N° {info['entrega_nro']} guardada por ${info['total']:,.2f}. PDF: {filename}")
                    ss.ent_items = []
                    ss.particular_nombre = ""
                    ss.show_entrega_modal = False
                    ss.modal_entrega_id = None
                    ss.modal_entrega_nro = None
                    st.rerun()
                except Exception as e:
                    st.warning(f"No se pudo guardar: {e}")

    # ---------------- Historial ----------------
    st.markdown("---")
    st.subheader("Historial")

    data = db.get_entregas_historial()
    if not data:
        st.info("Sin entregas.")
    else:
        for r in data:
            try:
                r["fecha_fmt"] = pd.to_datetime(r["fecha"], errors="coerce").strftime("%d/%m/%y")
            except Exception:
                r["fecha_fmt"] = r["fecha"]

        hdr = st.columns([0.8, 2.2, 1.3, 1.2, 1.0, 1.0, 1.0, 1.2])
        hdr[0].markdown("**N°**")
        hdr[1].markdown("**Cliente**")
        hdr[2].markdown("**Fecha**")
        hdr[3].markdown("**Monto**")
        hdr[4].markdown("**Detalles**")
        hdr[5].markdown("**Borrar**")
        hdr[6].markdown("**PDF**")
        hdr[7].markdown("**Descargar**")

        for r in data:
            c0, c1, c2, c3, c4, c5, c6, c7 = st.columns([0.8, 2.2, 1.3, 1.2, 1.0, 1.0, 1.0, 1.2])
            c0.write(r["entrega_nro"])
            c1.write(r["cliente"])
            c2.write(r["fecha_fmt"])
            c3.write(f"{r['total']:,.0f}")

            if c4.button("🔎", key=f"det_ent_{r['id']}"):
                st.session_state.show_entrega_modal = True
                st.session_state.modal_entrega_id = r["id"]
                st.session_state.modal_entrega_nro = r["entrega_nro"]
                st.rerun()

            if c5.button("✖", key=f"del_ent_{r['id']}"):
                pdf_path, _ = _pdf_path_for_row(r)
                try:
                    if pdf_path.exists():
                        pdf_path.unlink()
                except Exception:
                    pass
                db.delete_entrega(r["id"])
                st.success(f"Entrega N° {r['entrega_nro']} eliminada.")
                st.rerun()

            if c6.button("PDF", key=f"pdf_{r['id']}"):
                st.session_state.show_entrega_modal = False
                st.session_state.modal_entrega_id = None
                st.session_state.modal_entrega_nro = None
                pdf_path, filename = _pdf_path_for_row(r)
                if pdf_path.exists():
                    _open_pdf_new_tab(pdf_path.read_bytes(), filename)
                else:
                    _regenerate_and_offer_pdf(r, open_new_tab=True)

            with c7:
                pdf_path, filename = _pdf_path_for_row(r)
                if pdf_path.exists():
                    st.download_button("⬇️", data=pdf_path.read_bytes(),
                                       file_name=filename, mime="application/pdf",
                                       key=f"dl_{r['id']}")
                else:
                    pdf_bytes, _, filename = _build_pdf_for_entrega(
                        r["id"], r["entrega_nro"], r["cliente"], r["fecha"]
                    )
                    st.download_button("⬇️", data=pdf_bytes, file_name=filename,
                                       mime="application/pdf", key=f"dl_reg_{r['id']}")

    if ss.get("show_entrega_modal") and ss.get("modal_entrega_id"):
        _open_entrega_dialog(ss.modal_entrega_id, ss.modal_entrega_nro)

    _fixed_bar()  # barra fija con botón Subir


# ================= Helpers =================

def _sanitize_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[^\w\-\.\s]", "", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name)
    return name


def _client_folder(cliente: str, rev_id: int | None) -> Path:
    if rev_id is None:
        return Path(__file__).resolve().parents[1] / "data" / "pdfs" / "particulares"
    return Path(__file__).resolve().parents[1] / "data" / "pdfs" / _sanitize_name(cliente)


def _base_filename(cliente: str, fecha_iso: str, entrega_nro: int) -> str:
    d = datetime.strptime(fecha_iso, "%Y-%m-%d")
    cliente_print = cliente.replace("Particular ", "") if cliente.lower().startswith("particular ") else cliente
    cliente_print = _sanitize_name(cliente_print).upper()
    return f"ENTREGA DE MERCADERIA - {cliente_print} {d.day}-{d.month} N{entrega_nro}.pdf"


def _unique_path(path: Path) -> Path:
    if not path.exists(): return path
    stem, parent, suffix = path.stem, path.parent, path.suffix
    i = 2
    while True:
        p = parent / f"{stem} ({i}){suffix}"
        if not p.exists(): return p
        i += 1


def _find_existing_legacy_pdf(folder: Path, cliente: str, fecha_iso: str) -> Path | None:
    try:
        d = datetime.strptime(fecha_iso, "%Y-%m-%d")
        legacy_stem = f"ENTREGA DE MERCADERIA - {_sanitize_name(cliente).upper()} {d.day}-{d.month}"
        candidates = [Path(p) for p in glob(str(folder / f"{legacy_stem}*.pdf"))]
        if not candidates: return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]
    except Exception:
        return None


def _pdf_path_for_row(r) -> tuple[Path, str]:
    folder = _client_folder(r["cliente"], r["rev_id"])
    folder.mkdir(parents=True, exist_ok=True)
    exact = folder / _base_filename(r["cliente"], r["fecha"], r["entrega_nro"])
    if exact.exists(): return exact, exact.name
    legacy = _find_existing_legacy_pdf(folder, r["cliente"], r["fecha"])
    if legacy and legacy.exists(): return legacy, legacy.name
    return exact, exact.name


def _build_pdf_for_entrega(entrega_id: int, entrega_nro: int, cliente: str, fecha_iso: str):
    """Genera el PDF con ReportLab (via lib/pdfgen.py) y evita pisar archivos."""
    ent = db.get_entrega(entrega_id)
    items = db.get_entrega_items(entrega_id) or []

    folder = _client_folder(ent["cliente"], ent["rev_id"])
    folder.mkdir(parents=True, exist_ok=True)
    out_path = folder / _base_filename(cliente, fecha_iso, entrega_nro)
    out_path = _unique_path(out_path)

    pdf_bytes, final_path = build_entrega_pdf(cliente, fecha_iso, items, out_path)
    return pdf_bytes, final_path, Path(final_path).name


def _open_pdf_new_tab(pdf_bytes: bytes, filename: str):
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    html = f"""
    <script>
    (function(){{
      const b64 = "{b64}";
      const byteChars = atob(b64);
      const bytes = new Uint8Array(byteChars.length);
      for (let i=0;i<byteChars.length;i++) bytes[i] = byteChars.charCodeAt(i);
      const blob = new Blob([bytes], {{type: "application/pdf"}});
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
    }})();
    </script>
    """
    st.components.v1.html(html, height=0)


def _regenerate_and_offer_pdf(r, open_new_tab: bool = False):
    pdf_bytes, saved_path, filename = _build_pdf_for_entrega(
        entrega_id=r["id"], entrega_nro=r["entrega_nro"],
        cliente=r["cliente"], fecha_iso=r["fecha"]
    )
    if open_new_tab:
        _open_pdf_new_tab(pdf_bytes, filename)
    else:
        st.download_button("Descargar PDF", data=pdf_bytes, file_name=filename,
                           mime="application/pdf", key=f"dl_reg_{r['id']}")


def _open_entrega_dialog(entrega_id: int, entrega_nro: int):
    try:
        dialog = getattr(st, "dialog")
    except AttributeError:
        dialog = None

    if dialog:
        @dialog(f"Detalle Entrega N° {entrega_nro}")
        def _dlg():
            _render_modal_detalle(entrega_id)
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
<div id="modal"><h4>Detalle Entrega N° """ + str(entrega_nro) + """</h4></div>
""", unsafe_allow_html=True)
        _render_modal_detalle(entrega_id)


def _render_modal_detalle(entrega_id: int):
    items = db.get_entrega_items(entrega_id)
    if not items:
        st.info("Sin ítems.")
    else:
        df = pd.DataFrame(items)[["pieza", "cantidad", "precio", "total"]]
        st.dataframe(df, width="stretch")
    col1, col2 = st.columns([1, 1])
    if col1.button("Cerrar", key="close_ent_modal"):
        st.session_state.show_entrega_modal = False
        st.session_state.modal_entrega_id = None
        st.session_state.modal_entrega_nro = None
        st.rerun()


def _fixed_bar():
    # Igual que en detalle_revendedor.py pero SOLO con "↑ Subir"
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
  <a href="#top" target="_self">↑ Subir</a>
</div>
""", unsafe_allow_html=True)
