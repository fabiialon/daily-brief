"""Blackboard iCal feed: download, parse and classify today's and tomorrow's events."""
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from brief import net

try:
    from icalendar import Calendar
except ImportError:  # the standard-library parser below takes over
    Calendar = None

MADRID = ZoneInfo("Europe/Madrid")
MANAGEMENT_SUBJECT = "MANAGEMENT TOOLS & PRINCIPLES"
GRADABLE_PREFIX = "_blackboard.platform.gradebook2.GradableItem"
ENV_VAR = "BLACKBOARD_ICS_URL"

EXAM_RE = re.compile(r"\b(final exam|exam|midterm|quiz)\b", re.IGNORECASE)
SESSION_RE = re.compile(r"\(\s*Ses\.\s*(\d+)\s*\)", re.IGNORECASE)
NOISE_RE = re.compile(r"Live in-person|Asynchronous", re.IGNORECASE)
URL_RE = re.compile(r"https?://\S+")


class SourceError(Exception):
    """A data source failed. The message is safe to show; `causa` is the doctor's classification."""

    def __init__(self, message, causa=None):
        super().__init__(message)
        self.causa = causa


def sanitize(text, secret=None):
    """Remove the secret feed URL (and its path, which requests prints alone) and any other URL."""
    if secret:
        parts = urlsplit(secret)
        for piece in (secret, parts.path + ("?" + parts.query if parts.query else ""), parts.path):
            if len(piece) > 1:
                text = text.replace(piece, "<url>")
    return URL_RE.sub("<url>", text)


def download(url):
    """The raw feed, or SourceError with a classified cause. Never leaks the URL."""
    try:
        content = net.get(url).content
    except requests.RequestException as exc:
        msg = sanitize(f"{type(exc).__name__}: {exc}", url)
        # `from None` keeps the original exception (which contains the URL) out of any traceback.
        raise SourceError(msg, net.cause(exc, client_error="enlace_caducado")) from None
    if not content.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"BEGIN:VCALENDAR"):
        raise SourceError("el enlace no devuelve un calendario (¿página de login?)", "enlace_caducado")
    return content


def to_madrid(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=MADRID) if value.tzinfo is None else value.astimezone(MADRID)
    return datetime.combine(value, time(0), MADRID)  # all-day (VALUE=DATE)


def clean_subject(summary):
    text = NOISE_RE.sub("", SESSION_RE.sub("", summary))
    return re.sub(r"\s+", " ", text).strip()


def classify(summary, uid, start, end):
    if EXAM_RE.search(summary):
        return "examen"
    if uid.startswith(GRADABLE_PREFIX) or (start == end and (start.hour, start.minute) == (23, 59)):
        return "entrega"
    if re.search(r"Live in-person", summary, re.IGNORECASE):
        return "clase_presencial"
    if re.search(r"Asynchronous", summary, re.IGNORECASE):
        return "clase_asincrona"
    return "otro"


# --- Parsers: both yield plain dicts {SUMMARY, UID, LOCATION, DTSTART, DTEND} -------------------


def raw_events_icalendar(ics):
    out = []
    for comp in Calendar.from_ical(ics).walk("VEVENT"):
        out.append(
            {
                "SUMMARY": str(comp.get("SUMMARY", "")),
                "UID": str(comp.get("UID", "")),
                "LOCATION": str(comp.get("LOCATION", "")),
                "DTSTART": comp.decoded("DTSTART"),
                "DTEND": comp.decoded("DTEND") if comp.get("DTEND") is not None else None,
            }
        )
    return out


def _unescape(text):
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), text)


def _parse_dt(params, value):
    value = value.strip()
    if params.get("VALUE") == "DATE" or len(value) == 8:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    moment = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return moment.replace(tzinfo=timezone.utc)
    tzid = params.get("TZID", "").strip('"')
    if tzid:
        try:
            return moment.replace(tzinfo=ZoneInfo(tzid))
        except (ZoneInfoNotFoundError, ValueError):
            pass  # unknown zone: treated as floating, i.e. Madrid
    return moment


def raw_events_stdlib(ics):
    """Minimal RFC 5545 reader (standard library only), used when icalendar is missing or fails."""
    text = ics.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]", "", text)  # unfold continuation lines
    events, current, nested = [], None, 0
    for line in text.split("\n"):
        if line == "BEGIN:VEVENT":
            current, nested = {}, 0
        elif current is None or ":" not in line:
            continue
        elif line == "END:VEVENT":
            events.append(current)
            current = None
        elif line.startswith("BEGIN:"):
            nested += 1  # e.g. VALARM inside the event: its properties are not the event's
        elif line.startswith("END:"):
            nested -= 1
        elif nested == 0:
            head, value = line.split(":", 1)
            name, *params = head.split(";")
            current[name.upper()] = (dict(p.split("=", 1) for p in params if "=" in p), value)

    def text_of(ev, key):
        return _unescape(ev[key][1]) if key in ev else ""

    return [
        {
            "SUMMARY": text_of(ev, "SUMMARY"),
            "UID": text_of(ev, "UID"),
            "LOCATION": text_of(ev, "LOCATION"),
            "DTSTART": _parse_dt(*ev["DTSTART"]),
            "DTEND": _parse_dt(*ev["DTEND"]) if "DTEND" in ev else None,
        }
        for ev in events
    ]


def make_event(raw):
    """Plain dict from a parser -> (start in Madrid, brief event)."""
    summary, uid = raw["SUMMARY"], raw["UID"]
    start = to_madrid(raw["DTSTART"])
    if raw["DTEND"] is not None:
        end = to_madrid(raw["DTEND"])
    elif isinstance(raw["DTSTART"], datetime):
        end = start
    else:
        end = start + timedelta(days=1)
    session = SESSION_RE.search(summary)
    location = raw["LOCATION"].strip()
    return start, {
        "asignatura": clean_subject(summary),
        "sesion": int(session.group(1)) if session else None,
        "inicio": start.isoformat(),
        "fin": end.isoformat(),
        "aula": location or None,
        "tipo": classify(summary, uid, start, end),
    }


def parse_feed(ics):
    """All events as [(start, event)] sorted by start, plus True if the stdlib fallback was needed."""
    parsers = ([raw_events_icalendar] if Calendar is not None else []) + [raw_events_stdlib]
    for parser in parsers:
        try:
            events = sorted((make_event(raw) for raw in parser(ics)), key=lambda pair: pair[0])
            return events, parser is raw_events_stdlib
        except Exception as exc:  # try the next parser
            last = exc
    # Only the exception type: its text may quote feed lines (private data) and logs can be public.
    raise SourceError(f"no se pudo leer el calendario ({type(last).__name__})", "formato_cambiado") from None


def events_for(ics_bytes, day):
    """Events starting on `day` and the next day (Madrid time), sorted by start."""
    tomorrow = day + timedelta(days=1)
    events, _ = parse_feed(ics_bytes)
    # shortcut: events are bucketed by start date only; multi-day events don't repeat on later days.
    hoy = [e for start, e in events if start.date() == day]
    manana = [e for start, e in events if start.date() == tomorrow]
    return {
        "hoy": hoy,
        "manana": manana,
        "hay_management_hoy": any(e["asignatura"] == MANAGEMENT_SUBJECT for e in hoy),
    }


def feed_url():
    url = os.environ.get(ENV_VAR)
    if not url:
        raise SourceError(f"falta la variable de entorno {ENV_VAR}", "falta_configuracion")
    return url


def get_events(day: date):
    return events_for(download(feed_url()), day)
