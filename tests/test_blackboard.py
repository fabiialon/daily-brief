from datetime import date, datetime

import pytest
import requests

from brief import blackboard
from brief.blackboard import MADRID, classify, clean_subject, events_for

from conftest import FAKE_URL, FakeResponse


def by_name(events):
    return {e["asignatura"]: e for e in events}


def test_clean_subject_and_session(ics_bytes):
    ev = by_name(events_for(ics_bytes, date(2026, 11, 24))["hoy"])
    mtp = ev["MANAGEMENT TOOLS & PRINCIPLES"]
    assert (mtp["sesion"], mtp["aula"]) == (26, "Z-02.03")
    assert ev["MICROECONOMICS"]["sesion"] == 27
    assert ev["MICROECONOMICS"]["aula"] is None  # empty LOCATION
    assert ev["Group Homework"]["sesion"] is None and ev["Group Homework"]["aula"] is None
    assert clean_subject("  FOO   BAR  (Ses. 3)  Asynchronous ") == "FOO BAR"


def test_five_types_and_precedence(ics_bytes):
    hoy = by_name(events_for(ics_bytes, date(2026, 11, 24))["hoy"])
    manana = by_name(events_for(ics_bytes, date(2026, 11, 24))["manana"])
    assert hoy["MANAGEMENT TOOLS & PRINCIPLES"]["tipo"] == "clase_presencial"
    assert hoy["MICROECONOMICS"]["tipo"] == "clase_asincrona"
    assert hoy["Group Homework"]["tipo"] == "entrega"
    assert manana["Midterm - STATISTICS"]["tipo"] == "examen"  # GradableItem, but exam wins
    assert manana["Final Project"]["tipo"] == "entrega"  # bare "final" is not an exam
    assert manana["Example cases workshop"]["tipo"] == "clase_presencial"  # "Example" is not "exam"
    assert manana["Career fair"]["tipo"] == "otro"


@pytest.mark.parametrize(
    "summary,expected",
    [("Final Exam - LAW", "examen"), ("quiz 1", "examen"), ("EXAM review", "examen"), ("Examples", "otro"), ("Final", "otro")],
)
def test_exam_word_boundaries(summary, expected):
    t = datetime(2026, 1, 1, 10, tzinfo=MADRID)
    assert classify(summary, "x", t, t.replace(hour=11)) == expected


def test_deadline_by_time_without_gradable_uid():
    t = datetime(2026, 1, 1, 23, 59, tzinfo=MADRID)
    assert classify("Essay upload", "other-uid", t, t) == "entrega"


def test_timezones(ics_bytes):
    data = events_for(ics_bytes, date(2026, 11, 25))
    hoy = by_name(data["hoy"])
    assert hoy["Career fair"]["inicio"] == "2026-11-25T16:00:00+01:00"  # UTC -> Madrid
    assert hoy["Study group"]["inicio"] == "2026-11-25T18:00:00+01:00"  # floating = Madrid
    assert hoy["Campus holiday"]["inicio"] == "2026-11-25T00:00:00+01:00"  # all-day
    assert hoy["Campus holiday"]["fin"] == "2026-11-26T00:00:00+01:00"
    assert hoy["Late webinar"]["inicio"] == "2026-11-25T00:30:00+01:00"  # 23:30Z previous day
    assert hoy["Midterm - STATISTICS"]["inicio"] == "2026-11-25T09:00:00+01:00"  # TZID
    starts = [e["inicio"] for e in data["hoy"]]
    assert starts == sorted(starts)


def test_only_requested_day_and_next(ics_bytes):
    data = events_for(ics_bytes, date(2026, 11, 24))
    names = [e["asignatura"] for e in data["hoy"] + data["manana"]]
    assert "ORGANIZATIONAL BEHAVIOR" not in names  # previous day
    assert "Late webinar" not in [e["asignatura"] for e in data["hoy"]]


def test_month_change(ics_bytes):
    data = events_for(ics_bytes, date(2026, 11, 30))
    assert [e["asignatura"] for e in data["hoy"]] == ["MARKETING"]
    assert [(e["asignatura"], e["tipo"]) for e in data["manana"]] == [("Quiz 3 - PHYSICS", "examen")]


def test_empty_day(ics_bytes):
    assert events_for(ics_bytes, date(2026, 11, 27)) == {"hoy": [], "manana": [], "hay_management_hoy": False}


def test_management_flag(ics_bytes):
    assert events_for(ics_bytes, date(2026, 11, 24))["hay_management_hoy"] is True
    assert events_for(ics_bytes, date(2026, 11, 25))["hay_management_hoy"] is False
    assert events_for(ics_bytes, date(2026, 11, 23))["hay_management_hoy"] is False  # it's tomorrow, not today


def test_missing_env_var(monkeypatch):
    monkeypatch.delenv("BLACKBOARD_ICS_URL", raising=False)
    with pytest.raises(blackboard.SourceError, match="BLACKBOARD_ICS_URL"):
        blackboard.get_events(date(2026, 11, 24))


@pytest.mark.parametrize(
    "failure",
    [
        requests.Timeout(f"HTTPSConnectionPool(host='example.invalid', port=443): Read timed out. (url: {FAKE_URL})"),
        requests.ConnectionError(
            "HTTPSConnectionPool(host='example.invalid', port=443): Max retries exceeded with url: "
            "/webapps/calendar/calendarFeed/FAKEID123SECRET/learn.ics"
        ),
        "http500",
    ],
)
def test_feed_down_retries_with_backoff_and_hides_url(monkeypatch, failure, sleeps):
    calls = []

    def fake_get(url, timeout=None, **kw):
        calls.append(timeout)
        if failure == "http500":
            return FakeResponse(status=500)
        raise failure

    monkeypatch.setenv("BLACKBOARD_ICS_URL", FAKE_URL)
    monkeypatch.setattr(requests, "get", fake_get)
    with pytest.raises(blackboard.SourceError) as info:
        blackboard.get_events(date(2026, 11, 24))
    assert len(calls) == 4 and calls[0] == 20
    assert sleeps == [2, 4, 8]
    assert "FAKEID123SECRET" not in str(info.value) and "example.invalid/" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__
