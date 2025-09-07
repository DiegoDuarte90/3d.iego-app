from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image, Flowable
)
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER


# --------------------------
# Utilidades de formato
# --------------------------

def _miles(n: float) -> str:
    """$ 12.345 (sin decimales, separador de miles con punto)"""
    s = f"{int(round(n, 0)):,}".replace(",", ".")
    return f"$ {s}"

def _fecha_ddmmyyyy(iso: str) -> str:
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
        return f"{d.day}/{d.month}/{d.year}"
    except Exception:
        return iso

def _get_logo() -> Path:
    """
    Devuelve la ruta al logo OBLIGATORIO.
    Colocá data/logo.png o data/logo.jpg en la raíz del proyecto.
    """
    base = Path(__file__).resolve().parents[1]
    for p in [base / "data" / "logo.png", base / "data" / "logo.jpg"]:
        if p.exists():
            return p
    raise FileNotFoundError("No se encontró el logo en data/logo.png ni data/logo.jpg")


# Subrayado grueso para el título (simula el “subrayado” del ejemplo)
class Underline(Flowable):
    def __init__(self, width, thickness=1.6, color=colors.black, space=2):
        super().__init__()
        self.width = width
        self.thickness = thickness
        self.color = color
        self.space = space
        self.height = thickness + space
    def draw(self):
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, self.space, self.width, self.space)


# --------------------------
# Bloques (encabezado, tabla)
# --------------------------

def _build_header(cliente: str, fecha_iso: str, page_width: float):
    styles = getSampleStyleSheet()

    # Estilos “grandes” como el ejemplo
    st_label = ParagraphStyle("st_label", parent=styles["Normal"], fontSize=18, leading=22)
    st_value = ParagraphStyle("st_value", parent=styles["Normal"], fontSize=24, leading=28, spaceAfter=6)
    st_title = ParagraphStyle("st_title", parent=styles["Normal"], fontSize=36, leading=38, alignment=TA_LEFT)

    # Logo más grande
    logo_path = _get_logo()
    # 55mm x 55mm, y damos un poco más de ancho a la primera columna para que no “apreté” el título
    logo_w = logo_h = 55 * mm
    col_logo = 58 * mm

    logo = Image(str(logo_path), width=logo_w, height=logo_h)

    # Título en 2 líneas con subrayado grueso
    title_block = []
    title_block.append(Paragraph("<b>ENTREGA DE</b>", st_title))
    title_block.append(Underline(110*mm, thickness=1.6, color=colors.black, space=3))
    title_block.append(Paragraph("<b>MERCADERIA</b>", st_title))

    nombre = Paragraph('<font size="18"><b>Nombre:</b></font>', st_label)
    nombre_val = Paragraph(f"<b>{cliente.upper()}</b>", st_value)
    fecha = Paragraph('<font size="18"><b>Fecha:</b></font>', st_label)
    fecha_val = Paragraph(f"<b>{_fecha_ddmmyyyy(fecha_iso)}</b>", st_value)

    info_tbl = Table([[nombre, nombre_val],
                      [fecha,  fecha_val]],
                     colWidths=[35*mm, 80*mm])
    info_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))

    right = Table([[Table([[item] for item in title_block], colWidths=[110*mm])],
                   [info_tbl]],
                  colWidths=[110*mm])
    right.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))

    header = Table([[logo, right]], colWidths=[col_logo, page_width - col_logo])
    header.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 0),
    ]))
    return header


def _build_items_table(items: List[Dict], width: float) -> Table:
    styles = getSampleStyleSheet()

    # Encabezado grande y centrado
    st_head = ParagraphStyle("st_head", parent=styles["Normal"], fontSize=20, leading=22, alignment=TA_CENTER)
    # Filas
    st_cell = ParagraphStyle("st_cell", parent=styles["Normal"], fontSize=14, leading=16, alignment=TA_LEFT)
    st_num  = ParagraphStyle("st_num",  parent=styles["Normal"], fontSize=14, leading=16, alignment=TA_RIGHT)
    # Total row styles
    st_total_left  = ParagraphStyle("st_total_left",  parent=styles["Normal"], fontSize=22, leading=24, alignment=TA_CENTER)
    st_total_right = ParagraphStyle("st_total_right", parent=styles["Normal"], fontSize=26, leading=28, alignment=TA_RIGHT)

    # Anchos como el ejemplo
    col_c = 22 * mm
    col_precio = 42 * mm
    col_total  = 42 * mm
    col_art = max(60 * mm, width - (col_c + col_precio + col_total))

    data = [
        [Paragraph("<b>Artículo</b>", st_head),
         Paragraph("<b>C</b>", st_head),
         Paragraph("<b>Precio</b>", st_head),
         Paragraph("<b>Total</b>", st_head)]
    ]

    total_val = 0.0
    for it in items:
        pieza  = str(it.get("pieza", "")).strip().replace("\n", "<br/>")
        cant   = int(it.get("cantidad", 0))
        precio = float(it.get("precio", 0))
        tot    = float(it.get("total", cant * precio))
        total_val += tot
        data.append([
            Paragraph(pieza, st_cell),
            Paragraph(str(cant), st_head),             # centrado
            Paragraph(_miles(precio), st_num),
            Paragraph(_miles(tot), st_num),
        ])

    # ---- Fila de TOTAL al final (dentro de la tabla) ----
    idx_total = len(data)  # índice de la nueva fila
    data.append([
        Paragraph("<b>Total Final:</b>", st_total_left),
        "", "",  # se van a combinar (SPAN)
        Paragraph(f"<b>{_miles(total_val)}</b>", st_total_right),
    ])

    tbl = Table(data, colWidths=[col_art, col_c, col_precio, col_total], repeatRows=1)
    tbl.setStyle(TableStyle([
        # Bordes gruesos
        ("BOX", (0,0), (-1,-1), 1.4, colors.black),
        ("INNERGRID", (0,0), (-1,-2), 0.9, colors.black),  # hasta la penúltima (evitamos duplicar línea del total)

        # Cabecera
        ("BACKGROUND", (0,0), (-1,0), colors.white),
        ("LINEBELOW", (0,0), (-1,0), 1.4, colors.black),

        # Alineaciones / paddings
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN",  (1,1), (1,-2), "CENTER"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),

        # ---- Estilos de la fila TOTAL ----
        ("SPAN", (0, idx_total), (2, idx_total)),                # "Total Final:" ocupa columnas 0..2
        ("LINEABOVE", (0, idx_total), (-1, idx_total), 1.6, colors.black),  # línea gruesa sobre el total
        ("ALIGN", (0, idx_total), (2, idx_total), "CENTER"),
        ("RIGHTPADDING", (3, idx_total), (3, idx_total), 6),
    ]))
    return tbl


# --------------------------
# Generador principal
# --------------------------

def build_entrega_pdf(cliente: str, fecha_iso: str, items: List[Dict], out_path: Path) -> Tuple[bytes, str]:
    """
    Genera el PDF de la entrega con la estética del ejemplo.
    - Logo grande a la izquierda (data/logo.png|jpg)
    - Título grande subrayado
    - Nombre/Fecha grandes
    - Tabla con bordes gruesos; TOTAL integrado como última fila (con línea gruesa arriba)
    - Formato monetario $ 7.000
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=14*mm, rightMargin=14*mm,
        topMargin=10*mm, bottomMargin=14*mm,
        title=f"Entrega {cliente}"
    )
    page_w = A4[0] - doc.leftMargin - doc.rightMargin

    # Bloques
    header = _build_header(cliente, fecha_iso, page_w)
    items_tbl = _build_items_table(items, page_w)

    # Story: encabezado + tabla (el total ya va dentro de la tabla)
    story = [header, Spacer(0, 6), items_tbl]

    doc.build(story)
    return out_path.read_bytes(), str(out_path)
