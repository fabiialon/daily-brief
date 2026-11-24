import json
from datetime import date

import pytest
import requests

from brief import __main__ as cli
from brief import blackboard, doctor, health
from brief.blackboard import make_event, parse_feed, raw_events_icalendar, raw_events_stdlib

from conftest import FAKE_URL, FakeResponse

DAY = date(2026, 11, 24)
SECRET_ID = "FAKEID123SECRET"


def events_with(parser, ics):
    return sorted((make_event(raw) for raw in parser(ics)), key=lambda pair: pair[0])


# --- Fallback parser -----------------------------------------------------------------------------


def test_parsers_agree_on_fixture(ics_bytes):
    assert events_with(raw_events_stdlib, ics_bytes) == events_with(raw_events_icalendar, ics_bytes)


def test_parsers_agree_on_tricky_input():
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        "BEGIN:VEVENT\r\nUID:a-1\r\n"
        "SUMMARY:FOLDED SUBJECT NAME  (Ses. 4) Live\r\n  in-person\r\n"  # folded line
        "DTSTART;TZID=Europe/Madrid:20261124T090000\r\nDTEND;TZID=Europe/Madrid:20261124T100000\r\n"
        "LOCATION:Room 1\\, floor 2\r\n"  # escaped comma
        "BEGIN:VALARM\r\nACTION:DISPLAY\r\nSUMMARY:alarm text\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    ).encode()
    stdlib = events_with(raw_events_stdlib, ics)
    assert stdlib == events_with(raw_events_icalendar, ics)
    [(_, ev)] = stdlib
    assert (ev["asignatura"], ev["sesion"], ev["aula"], ev["tipo"]) == (
        "FOLDED SUBJECT NAME",
        4,
        "Room 1, floor 2",
        "clase_presencial",
    )


def test_fallback_when_icalendar_missing(monkeypatch, ics_bytes):
    normal, repaired = parse_feed(ics_bytes)
    assert repaired is False
    monkeypatch.setattr(blackboard, "Calendar", None)
    fallback, repaired = parse_feed(ics_bytes)
    assert repaired is True and fallback == normal


def test_fallback_when_icalendar_fails(monkeypatch, ics_bytes):
    def broken(_):
        raise ValueError("SUMMARY:PRIVATE TEXT could not be parsed")

    monkeypatch.setattr(blackboard.Calendar, "from_ical", staticmethod(broken))
    events, repaired = parse_feed(ics_bytes)
    assert repaired is True and len(events) == 13


def test_both_parsers_fail_without_leaking_content(monkeypatch):
    def broken(_):
        raise ValueError("DTSTART:PRIVATE TEXT")

    monkeypatch.setattr(blackboard.Calendar, "from_ical", staticmethod(broken))
    bad = b"BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:PRIVATE TEXT\nDTSTART:not-a-date\nEND:VEVENT\nEND:VCALENDAR\n"
    with pytest.raises(blackboard.SourceError) as info:
        parse_feed(bad)
    assert info.value.causa == "formato_cambiado"
    assert "PRIVATE" not in str(info.value)


# --- Download classification ---------------------------------------------------------------------


def serve(monkeypatch, *items):
    """Fake requests.get returning/raising the given items in order (last one repeats)."""
    items = list(items)

    def fake_get(url, params=None, headers=None, timeout=None):
        item = items.pop(0) if len(items) > 1 else items[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(requests, "get", fake_get)


@pytest.mark.parametrize(
    "response,causa",
    [
        (FakeResponse(status=401), "enlace_caducado"),
        (FakeResponse(status=403), "enlace_caducado"),
        (FakeResponse(status=404), "enlace_caducado"),
        (FakeResponse(content=b"<!DOCTYPE html><html>Login</html>"), "enlace_caducado"),
        (FakeResponse(status=500), "servicio_caido"),
        (FakeResponse(status=429), "limite_peticiones"),
        (requests.Timeout(f"Read timed out (url: {FAKE_URL})"), "servicio_caido"),
        (requests.exceptions.ProxyError(f"Unable to connect to proxy (url: {FAKE_URL})"), "dominio_bloqueado"),
        (requests.ConnectionError(f"Connection refused (url: {FAKE_URL})"), "dominio_bloqueado"),
    ],
)
def test_download_causes(monkeypatch, response, causa):
    serve(monkeypatch, response)
    with pytest.raises(blackboard.SourceError) as info:
        blackboard.download(FAKE_URL)
    assert info.value.causa == causa
    assert SECRET_ID not in str(info.value)


def test_download_recovers_after_network_error(monkeypatch, ics_bytes, sleeps):
    serve(monkeypatch, requests.ConnectionError("reset"), FakeResponse(content=b"\xef\xbb\xbf" + ics_bytes))
    assert blackboard.download(FAKE_URL).endswith(b"END:VCALENDAR\n")
    assert sleeps == [2]


# --- Doctor --------------------------------------------------------------------------------------


def by_source(report):
    return {f["fuente"]: f for f in report["fuentes"]}


def test_doctor_all_ok(fake_net):
    report = doctor.run(DAY)
    assert report["ok"] is True
    assert [(f["fuente"], f["estado"]) for f in report["fuentes"]] == [
        ("blackboard", "ok"),
        ("open-meteo", "ok"),
        ("met.no", "ok"),
    ]
    assert all(f["accion_usuario"] is None for f in report["fuentes"])


def test_doctor_missing_secret(fake_net, monkeypatch):
    monkeypatch.delenv("BLACKBOARD_ICS_URL")
    bb = by_source(doctor.run(DAY))["blackboard"]
    assert (bb["estado"], bb["causa"]) == ("fallo", "falta_configuracion")
    assert "gh secret set BLACKBOARD_ICS_URL" in bb["accion_usuario"]


def test_doctor_expired_link_never_shows_url(fake_net):
    fake_net["status"]["blackboard"] = 403
    report = doctor.run(DAY)
    bb = by_source(report)["blackboard"]
    assert report["ok"] is False
    assert (bb["estado"], bb["causa"]) == ("fallo", "enlace_caducado")
    assert "enlace iCal nuevo" in bb["accion_usuario"]
    assert SECRET_ID not in json.dumps(report) and "example.invalid" not in json.dumps(report)


def test_doctor_blocked_domain(fake_net, monkeypatch):
    fake_net["timeout"].discard("blackboard")

    def refused(url, params=None, headers=None, timeout=None):
        raise requests.exceptions.ProxyError(f"403 Forbidden from proxy (url: {url})")

    monkeypatch.setattr(requests, "get", refused)
    bb = by_source(doctor.run(DAY))["blackboard"]
    assert bb["causa"] == "dominio_bloqueado" and "Blackboard" in bb["accion_usuario"]


def test_doctor_rate_limit_repaired_by_metno(fake_net):
    fake_net["status"]["open-meteo"] = 429
    report = doctor.run(DAY)
    om = by_source(report)["open-meteo"]
    assert (om["estado"], om["causa"]) == ("reparado", "limite_peticiones")
    assert report["ok"] is True


def test_doctor_both_weather_down(fake_net):
    fake_net["status"]["open-meteo"] = 503
    fake_net["timeout"].add("met.no")
    report = doctor.run(DAY)
    src = by_source(report)
    assert (src["open-meteo"]["estado"], src["open-meteo"]["causa"]) == ("fallo", "servicio_caido")
    assert (src["met.no"]["estado"], src["met.no"]["causa"]) == ("fallo", "servicio_caido")
    assert report["ok"] is False


def test_doctor_weather_format_change_is_not_hidden_by_fallback(fake_net):
    fake_net["json"]["open-meteo"] = {"unexpected": True}
    om = by_source(doctor.run(DAY))["open-meteo"]
    assert (om["estado"], om["causa"]) == ("fallo", "formato_cambiado")


def test_doctor_feed_all_other_is_format_change(fake_net):
    fake_net["ics"] = (
        b"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nSUMMARY:Secret Meeting 42\n"
        b"DTSTART;TZID=Europe/Madrid:20261124T100000\nDTEND;TZID=Europe/Madrid:20261124T110000\n"
        b"ORGANIZER;CN=Jane Doe:mailto:jane@example.invalid\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    bb = by_source(doctor.run(DAY))["blackboard"]
    assert (bb["estado"], bb["causa"]) == ("fallo", "formato_cambiado")
    shapes = "\n".join(bb["estructura"])
    assert "DTSTART;TZID=Europe/Madrid:99999999a999999" in shapes
    assert "ORGANIZER;CN=…:aaaaaa:aaaa@aaaaaaa.aaaaaaa" in shapes
    assert "Secret" not in shapes and "Jane" not in shapes and "42" not in shapes


def test_doctor_feed_without_events_is_format_change(fake_net):
    fake_net["ics"] = b"BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n"
    assert by_source(doctor.run(DAY))["blackboard"]["causa"] == "formato_cambiado"


def test_doctor_repaired_parser(fake_net, monkeypatch):
    monkeypatch.setattr(blackboard, "Calendar", None)
    report = doctor.run(DAY)
    assert by_source(report)["blackboard"]["estado"] == "reparado"
    assert report["ok"] is True


def test_cli_doctor_exit_codes(fake_net, capsys):
    assert cli.main(["--doctor", "--date", "2026-11-24"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    fake_net["status"]["blackboard"] = 404
    assert cli.main(["--doctor", "--date", "2026-11-24"]) == 1
    out = capsys.readouterr().out
    assert json.loads(out)["ok"] is False and SECRET_ID not in out


# --- Workflow decision ---------------------------------------------------------------------------


def report_with(*fuentes):
    return {"ok": all(f["estado"] != "fallo" for f in fuentes), "fuentes": list(fuentes)}


def test_plan_ok():
    p = health.plan(report_with(doctor.entry("blackboard", "ok"), doctor.entry("open-meteo", "reparado")), True)
    assert (p["ok"], p["needs_user"], p["needs_code"]) == (True, False, False)


def test_plan_user_action():
    p = health.plan(report_with(doctor.entry("blackboard", "fallo", "enlace_caducado", "HTTPError 403")), True)
    assert (p["ok"], p["needs_user"], p["needs_code"]) == (False, True, False)
    assert p["issue_title"] == "Blackboard: el enlace del calendario ha caducado"
    assert "enlace iCal nuevo" in p["issue_body"] and "gh workflow run health.yml" in p["issue_body"]


def test_plan_code_problems():
    fmt = report_with(doctor.entry("blackboard", "fallo", "formato_cambiado"))
    assert health.plan(fmt, True)["needs_code"] is True
    assert health.plan(report_with(doctor.entry("blackboard", "ok")), False)["needs_code"] is True
    assert health.plan(None, True)["needs_code"] is True  # the doctor crashed


def test_plan_transient_failure_opens_nothing():
    p = health.plan(report_with(doctor.entry("blackboard", "fallo", "servicio_caido")), True)
    assert (p["ok"], p["needs_user"], p["needs_code"]) == (False, False, False)


def test_health_main_writes_outputs(tmp_path, monkeypatch):
    report = tmp_path / "doctor.json"
    report.write_text(json.dumps(report_with(doctor.entry("blackboard", "fallo", "falta_configuracion"))), "utf-8")
    out, body = tmp_path / "out", tmp_path / "body.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    health.main([str(report), "success", str(body)])
    assert "needs_user=true" in out.read_text("utf-8") and "needs_code=false" in out.read_text("utf-8")
    assert "gh secret set" in body.read_text("utf-8")
