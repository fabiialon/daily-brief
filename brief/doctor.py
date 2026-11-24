"""`python -m brief --doctor`: check every source separately and classify each failure."""
import re
from datetime import datetime

from brief import blackboard, weather

REPO = "fabiialon/daily-brief"
# Causes only Fabián can fix (the workflow opens an issue) and causes fixed by changing code.
USER_CAUSES = {"enlace_caducado", "dominio_bloqueado", "falta_configuracion"}
CODE_CAUSES = {"formato_cambiado"}
HOSTS = {"blackboard": "Blackboard", "open-meteo": "api.open-meteo.com", "met.no": "api.met.no"}

SECRET_CMD = f'printf %s "$BLACKBOARD_ICS_URL" | gh secret set BLACKBOARD_ICS_URL --repo {REPO}'
ACTIONS = {
    "enlace_caducado": (
        "Genera un enlace iCal nuevo en Blackboard (Calendario → compartir/exportar el calendario), "
        f"actualiza el secreto del repo ({SECRET_CMD}) y pega el enlace nuevo en la tarea programada."
    ),
    "dominio_bloqueado": (
        "GitHub Actions no consigue conectar con {host}. Comprueba que {host} funciona desde tu navegador; "
        "si funciona, el servicio puede estar bloqueando a GitHub: revisa la issue y decide si desactivar esa comprobación."
    ),
    "falta_configuracion": f"Crea el secreto del repo con el enlace iCal de Blackboard: {SECRET_CMD}",
}


def entry(fuente, estado, causa=None, detalle=None):
    accion = ACTIONS.get(causa, "").format(host=HOSTS[fuente]) if estado == "fallo" and causa in USER_CAUSES else None
    return {"fuente": fuente, "estado": estado, "causa": causa, "accion_usuario": accion, "detalle": detalle}


def feed_structure(ics, limit=30):
    """Shape of the feed with every value masked, so code can be fixed without exposing private data."""
    shapes = []
    text = ics.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
    for line in text.split("\n"):
        if ":" not in line or line[:1] in " \t":
            continue
        head, value = line.split(":", 1)
        name, *params = head.split(";")
        params = [p if p.split("=")[0] in ("TZID", "VALUE") else p.split("=")[0] + "=…" for p in params]
        masked = re.sub(r"\d", "9", re.sub(r"[^\W\d_]", "a", value))[:40]
        shape = ";".join([name, *params]) + ":" + masked
        if shape not in shapes:
            shapes.append(shape)
        if len(shapes) >= limit:
            break
    return shapes


def check_blackboard():
    try:
        ics = blackboard.download(blackboard.feed_url())
    except blackboard.SourceError as exc:
        return entry("blackboard", "fallo", exc.causa, str(exc))
    try:
        events, repaired = blackboard.parse_feed(ics)
    except blackboard.SourceError as exc:
        return dict(entry("blackboard", "fallo", exc.causa, str(exc)), estructura=feed_structure(ics))
    plausible = [start for start, _ in events if 2000 <= start.year <= 2100]
    problem = None
    if not plausible:
        problem = "el calendario no tiene eventos con fecha válida"
    elif all(e["tipo"] == "otro" for _, e in events):
        problem = "todos los eventos salen como tipo 'otro'"
    if problem:
        return dict(entry("blackboard", "fallo", "formato_cambiado", problem), estructura=feed_structure(ics))
    if repaired:
        return entry("blackboard", "reparado", None, "icalendar no disponible o falló: se usó el parser de reserva")
    return entry("blackboard", "ok")


def check_weather(name, fetch, day):
    try:
        fetch(day)
        return entry(name, "ok")
    except Exception as exc:
        return entry(name, "fallo", weather.failure_cause(exc), blackboard.sanitize(f"{type(exc).__name__}: {exc}"))


def run(day=None):
    day = day or datetime.now(blackboard.MADRID).date()
    fuentes = [check_blackboard()] + [check_weather(name, fetch, day) for name, fetch in weather.PROVIDERS]
    open_meteo, metno = fuentes[1], fuentes[2]
    # The weather chain repairs itself: a provider that is down while the other works is "reparado",
    # unless the cause is a code problem, which should still be fixed.
    for broken, other in ((open_meteo, metno), (metno, open_meteo)):
        if broken["estado"] == "fallo" and other["estado"] == "ok" and broken["causa"] not in CODE_CAUSES:
            broken["estado"] = "reparado"
    return {"ok": all(f["estado"] != "fallo" for f in fuentes), "fuentes": fuentes}
