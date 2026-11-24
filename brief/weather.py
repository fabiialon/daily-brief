"""Madrid daily forecast from Open-Meteo (no API key)."""
from datetime import date

import requests

API_URL = "https://api.open-meteo.com/v1/forecast"
PARAMS = {
    "latitude": 40.4168,
    "longitude": -3.7038,
    "timezone": "Europe/Madrid",
    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
    "hourly": "precipitation_probability,weather_code",
}
RAIN_HOUR_MIN = 40
UMBRELLA_MIN = 50
DAY_HOURS = range(8, 23)  # 8:00 to 22:00 inclusive

# WMO weather interpretation codes (Open-Meteo docs).
WMO = {
    0: ("☀️", "despejado"),
    1: ("🌤️", "casi despejado"),
    2: ("⛅", "parcialmente nublado"),
    3: ("☁️", "nublado"),
    45: ("🌫️", "niebla"),
    48: ("🌫️", "niebla con escarcha"),
    51: ("🌦️", "llovizna débil"),
    53: ("🌦️", "llovizna"),
    55: ("🌦️", "llovizna intensa"),
    56: ("🌧️", "llovizna helada débil"),
    57: ("🌧️", "llovizna helada intensa"),
    61: ("🌧️", "lluvia débil"),
    63: ("🌧️", "lluvia"),
    65: ("🌧️", "lluvia intensa"),
    66: ("🌧️", "lluvia helada débil"),
    67: ("🌧️", "lluvia helada intensa"),
    71: ("🌨️", "nieve débil"),
    73: ("🌨️", "nieve"),
    75: ("❄️", "nieve intensa"),
    77: ("🌨️", "granizo fino"),
    80: ("🌦️", "chubascos débiles"),
    81: ("🌧️", "chubascos"),
    82: ("⛈️", "chubascos fuertes"),
    85: ("🌨️", "chubascos de nieve débiles"),
    86: ("❄️", "chubascos de nieve fuertes"),
    95: ("⛈️", "tormenta"),
    96: ("⛈️", "tormenta con granizo débil"),
    99: ("⛈️", "tormenta con granizo fuerte"),
}
UNKNOWN = ("🌡️", "tiempo variable")


def rain_ranges(hours):
    """[13, 14, 15, 16] -> ["13–17 h"]: consecutive hours merged, end is exclusive."""
    ranges, start, prev = [], None, None
    for h in sorted(hours):
        if start is None:
            start = prev = h
        elif h == prev + 1:
            prev = h
        else:
            ranges.append(f"{start}–{prev + 1} h")
            start = prev = h
    if start is not None:
        ranges.append(f"{start}–{prev + 1} h")
    return ranges


def summarize(data, day: date):
    iso = day.isoformat()
    daily, hourly = data["daily"], data["hourly"]
    if daily.get("time") != [iso] or not all(t.startswith(iso) for t in hourly.get("time", [])):
        raise ValueError(f"Open-Meteo devolvió datos de otra fecha (pedida {iso}, recibida {daily.get('time')})")

    probs = {int(t[11:13]): p for t, p in zip(hourly["time"], hourly["precipitation_probability"]) if p is not None}
    day_probs = {h: p for h, p in probs.items() if h in DAY_HOURS}
    tramos = rain_ranges(h for h, p in day_probs.items() if p >= RAIN_HOUR_MIN)
    paraguas = max(day_probs.values(), default=0) >= UMBRELLA_MIN
    emoji, text = WMO.get(daily["weather_code"][0], UNKNOWN)
    tmax, tmin = round(daily["temperature_2m_max"][0]), round(daily["temperature_2m_min"][0])

    linea = f"🌡️ {tmin}–{tmax} °C · {text}"
    if tramos:
        linea += ", lluvia " + ", ".join(tramos)
    if paraguas:
        linea += " ☔ (llévate paraguas)"
    return {
        "max": tmax,
        "min": tmin,
        "prob_lluvia_max": daily["precipitation_probability_max"][0],
        "tramos_lluvia": tramos,
        "descripcion": f"{emoji} {text}",
        "paraguas": paraguas,
        "linea": linea,
    }


def get_weather(day: date):
    params = dict(PARAMS, start_date=day.isoformat(), end_date=day.isoformat())
    resp = requests.get(API_URL, params=params, timeout=20)
    resp.raise_for_status()
    return summarize(resp.json(), day)
