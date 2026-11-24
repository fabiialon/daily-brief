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

    def fake_get(url, params=None, timeout=None):
        seen.update(url=url, params=params, timeout=timeout)
        return FakeResponse(data=meteo)

    monkeypatch.setattr(requests, "get", fake_get)
    assert weather.get_weather(DAY)["max"] == 9
    assert seen["url"] == "https://api.open-meteo.com/v1/forecast"
    assert seen["params"]["start_date"] == seen["params"]["end_date"] == "2026-11-24"
    assert seen["params"]["timezone"] == "Europe/Madrid"
