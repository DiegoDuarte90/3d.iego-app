# lib/db.py
import os
import sqlite3
from pathlib import Path
from datetime import datetime

# --------------------------------------------------------------------
# Ruta del archivo SQLite: <proyecto>/data/app.db
# --------------------------------------------------------------------
DB_PATH = Path(__file__).resolve().parents[1] / "data" / "app.db"

# --------------------------------------------------------------------
# DDL base (revendedores + movimientos)
# --------------------------------------------------------------------
DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS revendedores (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre   TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS movimientos (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  rev_id       INTEGER NOT NULL,
  fecha        TEXT NOT NULL,                                  -- YYYY-MM-DD
  tipo         TEXT NOT NULL CHECK (tipo IN ('pago','devolucion','entrega')),
  detalle      TEXT NOT NULL,
  cantidad     INTEGER NOT NULL DEFAULT 0,
  monto        REAL NOT NULL DEFAULT 0,                         -- valor positivo
  medio_pago   TEXT,                                            -- MP / Efectivo (para pagos)
  entrega_nro  INTEGER,                                         -- referencia de entrega (si aplica)
  FOREIGN KEY (rev_id) REFERENCES revendedores(id) ON DELETE CASCADE
);
"""

# --------------------------------------------------------------------
# DDL de ENTREGAS (cabecera + items)
# --------------------------------------------------------------------
DDL_ENTREGAS = """
CREATE TABLE IF NOT EXISTS entregas (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  entrega_nro  INTEGER UNIQUE,                       -- numeración global
  rev_id       INTEGER,                              -- NULL si es particular
  cliente      TEXT,                                 -- nombre libre si particular
  fecha        TEXT NOT NULL,                        -- YYYY-MM-DD
  total        REAL NOT NULL DEFAULT 0,
  mov_id       INTEGER,                              -- id del movimiento generado (si revendedor)
  FOREIGN KEY (rev_id) REFERENCES revendedores(id) ON DELETE SET NULL,
  FOREIGN KEY (mov_id) REFERENCES movimientos(id)   ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS entrega_items (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  entrega_id  INTEGER NOT NULL,
  pieza       TEXT NOT NULL,
  cantidad    INTEGER NOT NULL,
  precio      REAL NOT NULL,
  total       REAL NOT NULL,
  FOREIGN KEY (entrega_id) REFERENCES entregas(id) ON DELETE CASCADE
);
"""

# --------------------------------------------------------------------
# Conexión & setup
# --------------------------------------------------------------------
def get_conn():
    """Devuelve una conexión a SQLite con foreign keys activas."""
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Crea tablas si no existen (idempotente)."""
    with get_conn() as c:
        c.executescript(DDL)
        c.executescript(DDL_ENTREGAS)

# --------------------------------------------------------------------
# Revendedores
# --------------------------------------------------------------------
def add_revendedor(nombre: str) -> int:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("Nombre vacío")
    with get_conn() as c:
        cur = c.execute("INSERT INTO revendedores(nombre) VALUES (?)", (nombre,))
        return cur.lastrowid

def update_revendedor(rid: int, nombre: str):
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("Nombre vacío")
    with get_conn() as c:
        c.execute("UPDATE revendedores SET nombre=? WHERE id=?", (nombre, rid))

def delete_revendedor(rid: int):
    """Borra revendedor y, por FK, también sus movimientos."""
    with get_conn() as c:
        c.execute("DELETE FROM revendedores WHERE id=?", (rid,))

def get_revendedores(q: str | None = None):
    with get_conn() as c:
        if q:
            rows = c.execute(
                "SELECT id, nombre FROM revendedores WHERE nombre LIKE ? ORDER BY nombre",
                (f"%{q}%",),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT id, nombre FROM revendedores ORDER BY nombre"
            ).fetchall()
        return [{"id": r["id"], "nombre": r["nombre"], "balance": get_balance(r["id"], conn=c)} for r in rows]

def get_revendedor(rid: int):
    with get_conn() as c:
        r = c.execute("SELECT id, nombre FROM revendedores WHERE id=?", (rid,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "nombre": r["nombre"], "balance": get_balance(r["id"], conn=c)}

# --------------------------------------------------------------------
# Movimientos
# --------------------------------------------------------------------
def add_movimiento(
    rev_id: int,
    tipo: str,
    detalle: str,
    cantidad: int,
    monto: float,
    fecha: str | None = None,
    medio_pago: str | None = None,
    entrega_nro: int | None = None,
):
    """
    Agrega movimiento manual.
    tipo: 'pago' (suma), 'devolucion' (resta), 'entrega' (resta).
    """
    tipo = tipo.lower().strip()
    if tipo not in ("pago", "devolucion", "entrega"):
        raise ValueError("Tipo inválido")

    if not fecha:
        fecha = datetime.now().strftime("%Y-%m-%d")
    detalle = detalle.strip()

    with get_conn() as c:
        c.execute(
            """INSERT INTO movimientos(rev_id,fecha,tipo,detalle,cantidad,monto,medio_pago,entrega_nro)
               VALUES (?,?,?,?,?,?,?,?)""",
            (rev_id, fecha, tipo, detalle, int(cantidad), float(monto), medio_pago, entrega_nro),
        )

def get_movimientos(rev_id: int):
    with get_conn() as c:
        cur = c.execute(
            """SELECT id, fecha, tipo, detalle, cantidad, monto, medio_pago, entrega_nro
               FROM movimientos
               WHERE rev_id=?
               ORDER BY date(fecha) DESC, id DESC""",
            (rev_id,),
        )
        return [dict(r) for r in cur.fetchall()]

def get_salidas(rev_id: int):
    with get_conn() as c:
        cur = c.execute(
            "SELECT fecha, detalle, cantidad, monto FROM movimientos "
            "WHERE rev_id=? AND tipo='entrega' "
            "ORDER BY date(fecha) DESC, id DESC",
            (rev_id,),
        )
        return [dict(r) for r in cur.fetchall()]

def get_movimiento(mov_id: int):
    with get_conn() as c:
        r = c.execute(
            "SELECT id, rev_id, fecha, tipo, detalle, cantidad, monto, medio_pago, entrega_nro "
            "FROM movimientos WHERE id=?",
            (mov_id,),
        ).fetchone()
        return dict(r) if r else None

def update_movimiento(
    mov_id: int, *, fecha: str, tipo: str, detalle: str, cantidad: int, monto: float, medio_pago: str | None
):
    tipo = tipo.lower().strip()
    if tipo not in ("pago", "devolucion", "entrega"):
        raise ValueError("Tipo inválido")
    with get_conn() as c:
        c.execute(
            "UPDATE movimientos SET fecha=?, tipo=?, detalle=?, cantidad=?, monto=?, medio_pago=? WHERE id=?",
            (fecha, tipo, detalle.strip(), int(cantidad), float(monto), medio_pago, mov_id),
        )

# --------------------------------------------------------------------
# Balance
# --------------------------------------------------------------------
def get_balance(rev_id: int, conn: sqlite3.Connection | None = None) -> float:
    """
    Balance = sum(pagos) - sum(devoluciones y entregas)
    """
    close = False
    if conn is None:
        conn = get_conn()
        close = True

    pagos = conn.execute(
        "SELECT COALESCE(SUM(monto),0) FROM movimientos WHERE rev_id=? AND tipo='pago'",
        (rev_id,),
    ).fetchone()[0]

    restas = conn.execute(
        "SELECT COALESCE(SUM(monto),0) FROM movimientos WHERE rev_id=? AND tipo IN ('devolucion','entrega')",
        (rev_id,),
    ).fetchone()[0]

    if close:
        conn.close()

    return float(pagos) - float(restas)

# --------------------------------------------------------------------
# ENTREGAS (cabecera + items)
# --------------------------------------------------------------------
def _next_entrega_nro_global(conn: sqlite3.Connection) -> int:
    cur = conn.execute("SELECT COALESCE(MAX(entrega_nro),0) FROM entregas")
    return int(cur.fetchone()[0]) + 1

def save_entrega(*, rev_id: int | None, cliente: str | None, fecha: str,
                 items: list[dict]) -> dict:
    """
    Guarda una entrega.
    - Si rev_id es None => Particular (no toca movimientos).
    - Si rev_id tiene valor => crea movimiento 'entrega' que resta al balance.
    items: [{'pieza','cantidad','precio','total'}]
    Retorna {'entrega_id','entrega_nro','total'}.
    """
    if not items:
        raise ValueError("No hay ítems en la entrega.")
    total = float(sum(i["total"] for i in items))

    with get_conn() as c:
        nro = _next_entrega_nro_global(c)

        # Cabecera
        cur = c.execute(
            "INSERT INTO entregas(entrega_nro, rev_id, cliente, fecha, total) VALUES (?,?,?,?,?)",
            (nro, rev_id, (cliente or None), fecha, total),
        )
        entrega_id = cur.lastrowid

        # Ítems
        for it in items:
            c.execute(
                "INSERT INTO entrega_items(entrega_id,pieza,cantidad,precio,total) VALUES (?,?,?,?,?)",
                (entrega_id, it["pieza"].strip(), int(it["cantidad"]), float(it["precio"]), float(it["total"]))
            )

        mov_id = None
        if rev_id is not None:
            # Impactar balance con movimiento 'entrega'
            c.execute(
                """INSERT INTO movimientos(rev_id,fecha,tipo,detalle,cantidad,monto,medio_pago,entrega_nro)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (rev_id, fecha, "entrega", f"Entrega N°{nro}", 0, total, None, nro),
            )
            mov_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            c.execute("UPDATE entregas SET mov_id=? WHERE id=?", (mov_id, entrega_id))

    return {"entrega_id": entrega_id, "entrega_nro": nro, "total": total}

def get_entregas_historial():
    """Lista todas las entregas (revendedor o particular)."""
    with get_conn() as c:
        rows = c.execute(
            """SELECT e.id, e.entrega_nro, e.fecha, e.total, e.rev_id, e.cliente,
                      r.nombre AS rev_nombre
               FROM entregas e
               LEFT JOIN revendedores r ON r.id = e.rev_id
               ORDER BY e.entrega_nro DESC"""
        ).fetchall()
        out = []
        for r in rows:
            cliente = r["rev_nombre"] if r["rev_id"] else (r["cliente"] or "Particular")
            out.append({
                "id": r["id"],
                "entrega_nro": r["entrega_nro"],
                "fecha": r["fecha"],
                "total": r["total"],
                "cliente": cliente,
                "rev_id": r["rev_id"],
            })
        return out

def get_entrega_items(entrega_id: int):
    with get_conn() as c:
        rows = c.execute(
            "SELECT pieza, cantidad, precio, total FROM entrega_items WHERE entrega_id=? ORDER BY id",
            (entrega_id,)
        ).fetchall()
        return [dict(r) for r in rows]

def get_entrega(entrega_id: int):
    """Devuelve una entrega con cliente resuelto y fecha ISO."""
    with get_conn() as c:
        r = c.execute(
            """SELECT e.id, e.entrega_nro, e.fecha, e.total, e.rev_id, e.cliente,
                      r.nombre AS rev_nombre
               FROM entregas e
               LEFT JOIN revendedores r ON r.id = e.rev_id
               WHERE e.id=?""",
            (entrega_id,)
        ).fetchone()
        if not r:
            return None
        cliente = r["rev_nombre"] if r["rev_id"] else (r["cliente"] or "Particular")
        return {
            "id": r["id"],
            "entrega_nro": r["entrega_nro"],
            "fecha": r["fecha"],          # ISO YYYY-MM-DD
            "total": r["total"],
            "rev_id": r["rev_id"],
            "cliente": cliente
        }

def delete_entrega(entrega_id: int):
    """Borra entrega, sus ítems y, si corresponde, el movimiento asociado."""
    with get_conn() as c:
        mov = c.execute("SELECT mov_id FROM entregas WHERE id=?", (entrega_id,)).fetchone()
        if not mov:
            return
        mov_id = mov["mov_id"]
        c.execute("DELETE FROM entregas WHERE id=?", (entrega_id,))  # borra cascade items
        if mov_id:
            c.execute("DELETE FROM movimientos WHERE id=?", (mov_id,))
