import json
from datetime import date, timezone

from brief import __main__ as cli


def run(capsys, *args):
    assert cli.main(list(args)) == 0
    return json.loads(capsys.readouterr().out)


def test_cli_end_to_end(fake_net, capsys):
    out = run(capsys, "--date", "2026-11-24")
    assert (out["fecha"], out["manana"]) == ("2026-11-24", "2026-11-25")
    assert out["errores"] == []
    assert out["blackboard"]["hay_management_hoy"] is True
    assert [e["asignatura"] for e in out["blackboard"]["hoy"]] == [
        "MICROECONOMICS",
        "MANAGEMENT TOOLS & PRINCIPLES",
        "Group Homework",
    ]
    assert out["clima"]["paraguas"] is True
    assert out["clima_fuente"] == "open-meteo"


def test_cli_month_change(fake_net, capsys, meteo):
    meteo["daily"]["time"] = ["2026-11-30"]
    meteo["hourly"]["time"] = [t.replace("2026-11-24", "2026-11-30") for t in meteo["hourly"]["time"]]
    out = run(capsys, "--date", "2026-11-30")
    assert out["manana"] == "2026-12-01"
    assert out["blackboard"]["manana"][0]["asignatura"] == "Quiz 3 - PHYSICS"


def test_cli_blackboard_down(fake_net, capsys):
    fake_net["timeout"].add("blackboard")
    out = run(capsys, "--date", "2026-11-24")
    assert out["blackboard"] is None
    assert out["clima"]["max"] == 9
    assert [e["fuente"] for e in out["errores"]] == ["blackboard"]
    assert "FAKEID123SECRET" not in json.dumps(out)


def test_cli_weather_wrong_day(fake_net, capsys):
    out = run(capsys, "--date", "2026-11-25")  # both weather fixtures are for 2026-11-24
    assert out["clima"] is None and out["clima_fuente"] is None
    assert out["blackboard"]["hay_management_hoy"] is False
    assert out["errores"][0]["fuente"] == "clima"


def test_cli_open_meteo_429_falls_back_to_metno(fake_net, capsys, sleeps):
    fake_net["status"]["open-meteo"] = 429
    out = run(capsys, "--date", "2026-11-24")
    assert out["clima_fuente"] == "met.no"
    assert out["clima"]["tramos_lluvia"] == ["14–17 h"]
    assert out["errores"] == []
    assert sleeps == [2, 4, 8]


def test_cli_both_weather_providers_down(fake_net, capsys):
    fake_net["status"]["open-meteo"] = 503
    fake_net["timeout"].add("met.no")
    out = run(capsys, "--date", "2026-11-24")
    assert out["clima"] is None and out["clima_fuente"] is None
    assert out["blackboard"] is not None
    [err] = out["errores"]
    assert err["fuente"] == "clima"
    assert "open-meteo" in err["mensaje"] and "met.no" in err["mensaje"]
    assert "http" not in err["mensaje"] and "/v1/forecast" not in err["mensaje"]


def test_cli_missing_env(fake_net, capsys, monkeypatch):
    monkeypatch.delenv("BLACKBOARD_ICS_URL")
    out = run(capsys, "--date", "2026-11-24")
    assert out["blackboard"] is None
    assert out["errores"][0] == {"fuente": "blackboard", "mensaje": "falta la variable de entorno BLACKBOARD_ICS_URL"}


def test_cli_default_date_is_madrid(fake_net, capsys, monkeypatch):
    class FixedDatetime(cli.datetime):
        @classmethod
        def now(cls, tz=None):
            # 23:30 UTC on the 23rd is already the 24th in Madrid
            return cli.datetime(2026, 11, 23, 23, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(cli, "datetime", FixedDatetime)
    assert run(capsys)["fecha"] == date(2026, 11, 24).isoformat()
