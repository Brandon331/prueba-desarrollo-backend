"""Backend de la prueba de desarrollo.
Instalar:  pip install fastapi uvicorn psycopg2-binary
Correr:    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/pruebas ADMIN_TOKEN=tu_clave uvicorn main:app --port 8000
Alumno: http://localhost:8000/   Admin: http://localhost:8000/admin
"""
import os, random
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import psycopg2
from calif import grade
from psycopg2.extras import RealDictCursor, Json

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/pruebas")
ADMIN = os.getenv("ADMIN_TOKEN", "admin123")
D = os.path.dirname(os.path.abspath(__file__))
# id -> (nivel, título). Se conservan todas para poder mostrar entregas antiguas.
ACT = {
    "registro": ("Intermedio", "BancoLuz - Registro de usuarios"),
    "reserva": ("Intermedio", "HotelMar - Reserva de habitaciones"),
    "login": ("Intermedio", "AppSegura - Inicio de sesión con bloqueo"),
    "transfer": ("Avanzado", "BancoLuz - Transferencias entre cuentas"),
    "pedidos": ("Avanzado", "TiendaNova - Pedidos y estados"),
}
# Actividades que se asignan a usuarios nuevos: solo nivel intermedio.
POOL = ["registro", "reserva", "login"]

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def q(sql, a=(), one=False):
    c = psycopg2.connect(DSN)
    try:
        with c, c.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, a)
            if not cur.description:
                return None
            return cur.fetchone() if one else cur.fetchall()
    finally:
        c.close()


@app.on_event("startup")
def schema():
    q("""CREATE TABLE IF NOT EXISTS usuarios(
           id SERIAL PRIMARY KEY, nombre TEXT NOT NULL, correo TEXT UNIQUE NOT NULL,
           actividad_id TEXT NOT NULL, estado TEXT NOT NULL DEFAULT 'en curso',
           creado_en TIMESTAMPTZ DEFAULT now(), finalizado_en TIMESTAMPTZ);
         CREATE TABLE IF NOT EXISTS entregas(
           id SERIAL PRIMARY KEY, usuario_id INT UNIQUE REFERENCES usuarios(id),
           actividad_id TEXT, notas TEXT, historial JSONB, enviado_en TIMESTAMPTZ DEFAULT now());""")


class U(BaseModel):
    nombre: str
    correo: str


class F(BaseModel):
    correo: str
    actividad_id: str = ""
    notas: str = ""
    historial: list = []
    inicio: str | None = None


@app.post("/usuarios/update")
def usuarios_update(u: U):
    """Registra al usuario y le asigna una actividad al azar. Si el correo ya existe, conserva su actividad."""
    return q("""INSERT INTO usuarios(nombre,correo,actividad_id) VALUES(%s,%s,%s)
                ON CONFLICT(correo) DO UPDATE SET nombre=EXCLUDED.nombre RETURNING *""",
             (u.nombre.strip(), u.correo.strip().lower(), random.choice(POOL)), one=True)


@app.post("/finalizar_act")
def finalizar_act(f: F):
    u = q("SELECT id,actividad_id,estado FROM usuarios WHERE correo=%s", (f.correo.strip().lower(),), one=True)
    if not u:
        raise HTTPException(404, "Usuario no registrado")
    if u["estado"] == "finalizada":
        raise HTTPException(409, "La prueba ya fue enviada")
    q("INSERT INTO entregas(usuario_id,actividad_id,notas,historial) VALUES(%s,%s,%s,%s)",
      (u["id"], u["actividad_id"], f.notas, Json(f.historial)))
    q("UPDATE usuarios SET estado='finalizada', finalizado_en=now() WHERE id=%s", (u["id"],))
    return {"ok": True}


@app.get("/admin/usuarios")
def admin_usuarios(x_admin_token: str = Header("")):
    if x_admin_token != ADMIN:
        raise HTTPException(401, "Token inválido")
    rows = q("""SELECT u.*, e.notas, e.historial FROM usuarios u
                LEFT JOIN entregas e ON e.usuario_id=u.id ORDER BY u.creado_en DESC""")
    for r in rows:
        r["nivel"], r["titulo"] = ACT.get(r["actividad_id"], ("", r["actividad_id"]))
        r["calif"] = grade(r["actividad_id"], r["notas"], r["historial"]) if r["estado"] == "finalizada" else None
    return rows


@app.get("/")
def alumno():
    return FileResponse(os.path.join(D, "index.html"))


@app.get("/admin")
def admin():
    return FileResponse(os.path.join(D, "admin.html"))