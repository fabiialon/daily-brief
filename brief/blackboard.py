"""Blackboard iCal feed: download, parse and classify today's and tomorrow's events."""
import os
import re
from datetime import date, datetime, time, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests
from icalendar import Calendar

MADRID = ZoneInfo("Europe/Madrid")
MANAGEMENT_SUBJECT = "MANAGEMENT TOOLS & PRINCIPLES"
GRADABLE_PREFIX = "_blackboard.platform.gradebook2.GradableItem"
ENV_VAR = "BLACKBOARD_ICS_URL"

EXAM_RE = re.compile(r"\b(final exam|exam|midterm|quiz)\b", re.IGNORECASE)
SESSION_RE = re.compile(r"\(\s*Ses\.\s*(\d+)\s*\)", re.IGNORECASE)
NOISE_RE = re.compile(r"Live in-person|Asynchronous", re.IGNORECASE)
URL_RE = re.compile(r"https?://\S+")


class SourceError(Exception):
    """A data source failed; the message is already safe to show."""


def sanitize(text, secret=None):
    """Remove the secret feed URL (and its path, which requests prints alone) and any other URL."""
    if secret:
        parts = urlsplit(secret)
        for piece in (secret, parts.path + ("?" + parts.query if parts.query else ""), parts.path):
            if len(piece) > 1:
                text = text.replace(piece, "<url>")
    return URL_RE.sub("<url>", text)


def fetch_ics(url, timeout=20, retries=1):
    last = None
    for _ in range(retries + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as exc:
            last = exc
    # `from None` keeps the original exception (which contains the URL) out of any traceback.
    raise SourceError(sanitize(f"{type(last).__name__}: {last}", url)) from None


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


def parse_event(comp):
    summary = str(comp.get("SUMMARY", ""))
    uid = str(comp.get("UID", ""))
    raw_start = comp.decoded("DTSTART")
    start = to_madrid(raw_start)
    if comp.get("DTEND") is not None:
        end = to_madrid(comp.decoded("DTEND"))
    elif isinstance(raw_start, datetime):
        end = start
    else:
        end = start + timedelta(days=1)
    session = SESSION_RE.search(summary)
    location = str(comp.get("LOCATION", "")).strip()
    return {
        "asignatura": clean_subject(summary),
        "sesion": int(session.group(1)) if session else None,
        "inicio": start.isoformat(),
        "fin": end.isoformat(),
        "aula": location or None,
        "tipo": classify(summary, uid, start, end),
    }, start


def events_for(ics_bytes, day):
    """Events starting on `day` and the next day (Madrid time), sorted by start."""
    tomorrow = day + timedelta(days=1)
    buckets = {day: [], tomorrow: []}
    # shortcut: events are bucketed by start date only; multi-day events don't repeat on later days.
    for comp in Calendar.from_ical(ics_bytes).walk("VEVENT"):
        event, start = parse_event(comp)
        if start.date() in buckets:
            buckets[start.date()].append((start, event))
    hoy, manana = ([e for _, e in sorted(b, key=lambda x: x[0])] for b in (buckets[day], buckets[tomorrow]))
    return {
        "hoy": hoy,
        "manana": manana,
        "hay_management_hoy": any(e["asignatura"] == MANAGEMENT_SUBJECT for e in hoy),
    }


def get_events(day: date):
    url = os.environ.get(ENV_VAR)
    if not url:
        raise SourceError(f"falta la variable de entorno {ENV_VAR}")
    return events_for(fetch_ics(url), day)
