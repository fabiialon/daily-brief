from datetime import date

import pytest
import requests

from brief import weather
from brief.weather import rain_ranges, summarize

from conftest import FakeResponse

DAY = date(2026, 11, 24)


def test_summary_from_fixture(meteo):
    out = summarize(meteo, DAY)
    assert (out["max"], out["min"], out["prob_lluvia_max"]) == (9, 6, 90)
    # 60 % before 8 h and 90 % at 23 h are outside the 8–22 h window and ignored
    assert out["tramos_lluvia"] == ["13–17 h", "20–21 h"]
    assert out["paraguas"] is True
    assert out["descripcion"] == "☁️ nublado"
    assert out["linea"] == "🌡️ 6–9 °C · nublado, lluvia 13–17 h, 20–21 h ☔ (llévate paraguas)"


def test_no_umbrella_below_50(meteo):
    meteo["hourly"]["precipitation_probability"] = [45] * 24
    out = summarize(meteo, DAY)
    assert out["paraguas"] is False
    assert out["tramos_lluvia"] == ["8–23 h"]
    assert "paraguas" not in out["linea"]


def test_dry_day_line(meteo):
    meteo["hourly"]["precipitation_probability"] = [0] * 24
    meteo["daily"]["weather_code"] = [0]
    out = summarize(meteo, DAY)
    assert out["linea"] == "🌡️ 6–9 °C · despejado"


def test_unknown_wmo_code(meteo):
    meteo["daily"]["weather_code"] = [42]
    assert summarize(meteo, DAY)["descripcion"] == "🌡️ tiempo variable"


def test_wrong_date_raises(meteo):
    meteo["daily"]["time"] = ["2026-11-22"]
    with pytest.raises(ValueError, match="otra fecha"):
        summarize(meteo, DAY)


def test_wrong_hourly_date_raises(meteo):
    meteo["hourly"]["time"][5] = "2026-11-22T05:00"
    with pytest.raises(ValueError):
        summarize(meteo, DAY)


def test_rain_ranges():
    assert rain_ranges([]) == []
    assert rain_ranges([9]) == ["9–10 h"]
    assert rain_ranges([15, 13, 14, 18]) == ["13–16 h", "18–19 h"]


def test_get_weather_request(monkeypatch, meteo):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params, headers=headers, timeout=timeout)
        return FakeResponse(data=meteo)

    monkeypatch.setattr(requests, "get", fake_get)
    clima, fuente = weather.get_weather(DAY)
    assert (clima["max"], fuente) == (9, "open-meteo")
    assert seen["url"] == "https://api.open-meteo.com/v1/forecast"
    assert seen["params"]["start_date"] == seen["params"]["end_date"] == "2026-11-24"
    assert seen["params"]["timezone"] == "Europe/Madrid"
    assert seen["headers"]["User-Agent"].startswith("daily-brief/")


def scripted_get(monkeypatch, responses):
    """Fake requests.get that returns/raises the given items in order, recording each call's host."""
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(("met.no" if "met.no" in url else "open-meteo", headers["User-Agent"]))
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(requests, "get", fake_get)
    return calls


def test_429_then_success(monkeypatch, meteo, sleeps):
    calls = scripted_get(monkeypatch, [FakeResponse(status=429), FakeResponse(data=meteo)])
    clima, fuente = weather.get_weather(DAY)
    assert fuente == "open-meteo" and clima["max"] == 9
    assert sleeps == [2]
    assert [c[0] for c in calls] == ["open-meteo", "open-meteo"]


def test_5xx_retried_with_backoff(monkeypatch, meteo, sleeps):
    scripted_get(monkeypatch, [FakeResponse(status=500), FakeResponse(status=502), FakeResponse(status=503), FakeResponse(data=meteo)])
    assert weather.get_weather(DAY)[1] == "open-meteo"
    assert sleeps == [2, 4, 8]


def test_persistent_429_falls_back_to_metno(monkeypatch, metno, sleeps):
    calls = scripted_get(monkeypatch, [FakeResponse(status=429)] * 4 + [FakeResponse(data=metno)])
    clima, fuente = weather.get_weather(DAY)
    assert fuente == "met.no"
    assert sleeps == [2, 4, 8]
    assert [c[0] for c in calls] == ["open-meteo"] * 4 + ["met.no"]
    assert all(ua.startswith("daily-brief/1.0") for _, ua in calls)
    assert set(clima) == {"max", "min", "prob_lluvia_max", "tramos_lluvia", "descripcion", "paraguas", "linea"}


def test_no_retry_on_404(monkeypatch, metno, sleeps):
    scripted_get(monkeypatch, [FakeResponse(status=404), FakeResponse(data=metno)])
    assert weather.get_weather(DAY)[1] == "met.no"
    assert sleeps == []


def test_both_providers_down(monkeypatch, sleeps):
    scripted_get(
        monkeypatch,
        [FakeResponse(status=503, url="https://api.open-meteo.com/v1/forecast?x=1")] * 4
        + [requests.ConnectionError("Max retries exceeded with url: https://api.met.no/weatherapi/x")],
    )
    with pytest.raises(RuntimeError) as info:
        weather.get_weather(DAY)
    assert "open-meteo" in str(info.value) and "met.no" in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_metno_summary_estimates_rain_from_amount(metno):
    out = weather.summarize_metno(metno, DAY)
    # UTC -> Madrid: 13-15 h UTC with 0.5 mm are 14-16 h Madrid; 0.1 mm at 19 h is not rain;
    # 1 mm at 6 h counts for the daily max but is outside the 8-22 h window.
    assert out["tramos_lluvia"] == ["14–17 h"]
    assert out["paraguas"] is True
    assert out["prob_lluvia_max"] == 100
    assert (out["min"], out["max"]) == (5, 11)  # 2.0 at 23:00 on the 23rd is excluded
    assert out["descripcion"] == "☁️ nublado"
    assert out["linea"] == "🌡️ 5–11 °C · nublado, lluvia 14–17 h ☔ (llévate paraguas)"


def test_metno_uses_probability_when_given(metno):
    for entry in metno["properties"]["timeseries"]:
        entry["data"]["next_1_hours"]["details"]["probability_of_precipitation"] = 30
    out = weather.summarize_metno(metno, DAY)
    assert out["tramos_lluvia"] == [] and out["paraguas"] is False and out["prob_lluvia_max"] == 30


def test_metno_wrong_day_raises(metno):
    with pytest.raises(ValueError, match="met.no"):
        weather.summarize_metno(metno, date(2026, 11, 26))


@pytest.mark.parametrize(
    "symbol,code", [("lightrainshowers_day", 80), ("heavyrainandthunder", 95), ("cloudy", 3), ("newsymbol", None)]
)
def test_metno_symbol_mapping(symbol, code):
    assert weather.metno_code(symbol) == code
