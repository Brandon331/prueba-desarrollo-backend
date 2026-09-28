"""Calificación automática (0-100) de una entrega.
  10 pts  encontró el método correcto de la API (una petición que no dio 405/404)
  10 pts  hizo al menos una petición exitosa (2xx)
  80 pts  repartidos entre los bugs de su actividad. Por cada bug:
            50%  lo provocó en sus peticiones (evidencia en el historial)
            50%  además lo describió en su reporte (palabras clave) 
Un bug mencionado en las notas pero nunca provocado no suma.
Es una nota de apoyo: conviene revisar el reporte a mano."""
import json, re, unicodedata
from urllib.parse import urlparse


def _n(t):
    return re.sub(r"[\u0300-\u036f]", "", unicodedata.normalize("NFD", (t or "").lower()))


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _parse(h):
    out = []
    for x in h or []:
        if not isinstance(x, dict):
            continue
        try:
            b = json.loads(x["b"]) if x.get("b") else {}
        except Exception:
            b = {}
        r = x.get("r")
        out.append(dict(m=x.get("m"), p=urlparse(str(x.get("u", ""))).path, c=x.get("c"),
                        b=b if isinstance(b, dict) else {}, r=r if isinstance(r, dict) else {}))
    return out


EM = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _registro(H):
    E = [e for e in H if e["p"] == "/api/registro" and e["m"] == "POST"]
    pw = lambda e: str(e["b"].get("password", ""))
    return [
        any(e["c"] == 201 and not EM.match(str(e["b"].get("email", ""))) for e in E),
        any(e["c"] == 201 and len(pw(e)) >= 8 and not re.search(r"\d", pw(e)) for e in E),
        any(e["c"] == 403 and e["b"].get("edad") == 18 for e in E),
        any(e["c"] == 201 and e["b"].get("email") == "ana@mail.com" for e in E),
    ]


def _reserva(H):
    E = [e for e in H if e["p"] == "/api/reserva" and e["m"] == "POST" and e["c"] == 201]
    g = lambda e, k: str(e["b"].get(k, ""))
    return [
        any(g(e, "entrada") < "2026-09-27" for e in E),
        any(g(e, "entrada") == g(e, "salida") for e in E),
        any((_num(e["b"].get("huespedes")) or 0) > 4 for e in E),
        any(e["r"].get("noches") == 7 and e["r"].get("total") == 8400 for e in E),
    ]


def _login(H):
    run = 0
    b = [False] * 4
    seen = False
    for e in [e for e in H if e["p"] == "/api/login" and e["m"] == "POST"]:
        er = _n(str(e["r"].get("error", "")))
        if e["c"] == 401 and "incorrecta" in er:
            run += 1
        elif e["c"] == 423:
            b[0] |= run >= 3
            run, seen = 0, True
        elif e["c"] == 200:
            b[1] |= seen
            run = 0
        if e["c"] == 401 and "no existe" in er:
            b[2] = True
        if e["c"] == 500:
            b[3] = True
    return b


def _transfer(H):
    bal = {"A001": 8000, "A002": 500, "A003": 0}
    tot, seen, b = {}, {}, [False] * 6
    for e in H:
        c, r, bd = e["c"], e["r"], e["b"]
        m = re.match(r"^/api/cuentas/(\w+)$", e["p"])
        if m and e["m"] == "GET":
            if c == 200:
                if m.group(1) not in bal:
                    b[5] = True
                else:
                    bal[m.group(1)] = r.get("saldo", bal[m.group(1)])
            continue
        if e["p"] != "/api/transferir" or e["m"] != "POST":
            continue
        o, d, mo, k = bd.get("origen"), bd.get("destino"), _num(bd.get("monto")), bd.get("clave")
        if c == 422 and "insuficiente" in _n(str(r.get("error", ""))) and mo is not None and mo == bal.get(o):
            b[0] = True
        if c == 200:
            b[1] |= o == d
            b[4] |= mo is not None and round(mo, 2) != mo
            if k in seen and seen[k] != r.get("saldo_origen"):
                b[2] = True
            seen.setdefault(k, r.get("saldo_origen"))
            tot[o] = tot.get(o, 0) + (mo or 0)
            b[3] |= tot[o] > 5000
            if _num(r.get("saldo_origen")) is not None:
                bal[o] = r["saldo_origen"]
            if _num(r.get("saldo_destino")) is not None:
                bal[d] = r["saldo_destino"]
    return b


PR = {"LAP": 900, "MOU": 25, "TEC": 60}
OKT = {"creado": {"pagado", "cancelado"}, "pagado": {"enviado", "cancelado"}, "enviado": {"entregado"},
       "entregado": set(), "cancelado": set()}


def _pedidos(H):
    st, b = {}, [False] * 6
    for e in H:
        if e["m"] != "POST":
            continue
        c, r, bd = e["c"], e["r"], e["b"]
        if e["p"] == "/api/pedidos" and c == 201:
            its = [i for i in (bd.get("items") if isinstance(bd.get("items"), list) else []) if isinstance(i, dict)]
            ints = lambda q: isinstance(q, int) and not isinstance(q, bool)
            b[0] |= any(not ints(i.get("qty")) or i["qty"] < 1 for i in its)
            sub = sum(PR.get(i.get("sku"), 0) * i["qty"] for i in its if ints(i.get("qty")))
            b[1] |= sub == 1000 and r.get("total") == 1050
            st[r.get("id")] = r.get("estado", "creado")
            continue
        m = re.match(r"^/api/pedidos/(\w+)/estado$", e["p"])
        if m:
            b[5] |= c == 500
            if c == 200:
                pv, nw = st.get(m.group(1)), r.get("estado")
                if pv and nw not in OKT.get(pv, set()):
                    b[2] |= (pv, nw) == ("creado", "enviado")
                    b[3] |= (pv, nw) == ("enviado", "cancelado")
                    b[4] |= (pv, nw) == ("entregado", "creado")
                st[m.group(1)] = nw
    return b


RUB = {
    "registro": ("/api/registro", _registro, [
        ("Acepta emails con formato inválido (a@b, @)", r"a@b|(email|correo).{0,40}(inval|formato|dominio)|formato.{0,20}(email|correo)"),
        ("Acepta contraseñas de 8+ caracteres sin números", r"(contrasena|password|clave).{0,60}(numero|digito)|sin numero"),
        ("Rechaza a quien tiene exactamente 18 años", r"\b18\b"),
        ("Permite registrar un email ya existente (ana@mail.com)", r"ana@mail|repetid|duplicad|ya registrad|ya existe|409")]),
    "reserva": ("/api/reserva", _reserva, [
        ("Permite reservar con entrada en el pasado", r"pasad|2026-01|anterior|antes de hoy|fecha vieja"),
        ("Acepta salida igual a la entrada (0 noches)", r"(salida|misma|igual).{0,40}(entrada|fecha)|0 noches|cero noches"),
        ("No limita los huéspedes a 4", r"huesped|mas de 4|limite|maximo"),
        ("El descuento empieza en 8 noches y no en 7", r"descuento|7 noches|8 noches")]),
    "login": ("/api/login", _login, [
        ("Bloquea al 4.º intento fallido, no al 3.º", r"(3|tres|tercer|4|cuart).{0,30}intento|bloque"),
        ("Cuenta bloqueada entra con la clave correcta", r"bloquead.{0,80}correct|correct.{0,80}bloquead"),
        ("Revela si el usuario existe o no", r"no existe|revela|filtra|enumera|informacion del usuario"),
        ("Sin user/pass responde 500 en vez de 400", r"500|vacio|sin (user|pass|campos)|campos vacios")]),
    "transfer": ("/api/transferir", _transfer, [
        ("Rechaza transferir todo el saldo (debería dejar $0)", r"todo el saldo|saldo (total|completo|exacto)|monto igual|igual al saldo|en 0|\b0\b"),
        ("Acepta origen y destino iguales", r"origen.{0,30}destino|misma cuenta|cuentas iguales|iguales"),
        ("Idempotencia rota: misma clave vuelve a cobrar", r"idempoten|misma clave|clave repetida|duplic"),
        ("No controla el límite diario de $5000", r"5000|acumulad|diari|por dia"),
        ("Acepta más de 2 decimales", r"decimal|10\.555|flotante"),
        ("Cuenta inexistente devuelve 200 con saldo 0", r"no existe|inexistente|404|saldo 0")]),
    "pedidos": ("/api/pedidos", _pedidos, [
        ("Acepta qty 0, negativa o decimal", r"qty|cantidad|negativ|decimal|\b0\b"),
        ("Cobra envío con subtotal exacto de $1000", r"1000|envio gratis|gratis|envio"),
        ("Permite pasar de creado a enviado sin pagar", r"saltar|salto|sin pagar|creado.{0,20}enviado"),
        ("Permite cancelar un pedido ya enviado", r"cancel.{0,40}enviado|enviado.{0,40}cancel"),
        ("Un pedido entregado puede volver a creado", r"entregado.{0,50}(creado|volver|final)|estado final"),
        ("Cambiar estado de un id inexistente da 500", r"500|inexistente|no existe|404")]),
}


def grade(act, notas, hist):
    if act not in RUB:
        return None
    base, fn, bugs = RUB[act]
    H, t = _parse(hist), _n(notas)
    metodo = any(e["p"].startswith(base) and e["c"] not in (404, 405) and "json" not in _n(str(e["r"].get("error", "")))
                 for e in H)
    feliz = any(e["c"] in (200, 201) for e in H)
    each, pts, det = 80 / len(bugs), 0.0, []
    for (desc, rx), probado in zip(bugs, fn(H)):
        rep = bool(re.search(rx, t, re.S))
        pts += each * ((0.5 if probado else 0) + (0.5 if probado and rep else 0))
        det.append({"bug": desc, "probado": bool(probado), "reportado": rep})
    return {"nota": round(10 * metodo + 10 * feliz + pts), "metodo": metodo, "feliz": feliz, "bugs": det}