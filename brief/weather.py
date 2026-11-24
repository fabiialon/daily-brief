"""Madrid daily forecast from Open-Meteo (no API key)."""
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

from brief import net

API_URL = "https://api.open-meteo.com/v1/forecast"
PARAMS = {
    "latitude": 40.4168,
    "longitude": -3.7038,
    "timezone": "Europe/Madrid",
    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
    "hourly": "precipitation_probability,weather_code",
}
METNO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
METNO_PARAMS = {"lat": 40.4168, "lon": -3.7038}
MADRID = ZoneInfo("Europe/Madrid")
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

# met.no symbol_code base (without _day/_night/_polartwilight) -> closest WMO code.
METNO_TO_WMO = {
    "clearsky": 0, "fair": 1, "partlycloudy": 2, "cloudy": 3, "fog": 45,
    "lightrain": 61, "rain": 63, "heavyrain": 65,
    "lightrainshowers": 80, "rainshowers": 81, "heavyrainshowers": 82,
    "lightsleet": 66, "sleet": 67, "heavysleet": 67,
    "lightsleetshowers": 85, "sleetshowers": 85, "heavysleetshowers": 86,
    "lightsnow": 71, "snow": 73, "heavysnow": 75,
    "lightsnowshowers": 85, "snowshowers": 85, "heavysnowshowers": 86,
}


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


def build(tmax, tmin, prob_max, probs, code):
    """Common output for any provider. `probs` maps Madrid hour -> rain probability (%)."""
    day_probs = {h: p for h, p in probs.items() if h in DAY_HOURS}
    tramos = rain_ranges(h for h, p in day_probs.items() if p >= RAIN_HOUR_MIN)
    paraguas = max(day_probs.values(), default=0) >= UMBRELLA_MIN
    emoji, text = WMO.get(code, UNKNOWN)
    tmax, tmin = round(tmax), round(tmin)

    linea = f"🌡️ {tmin}–{tmax} °C · {text}"
    if tramos:
        linea += ", lluvia " + ", ".join(tramos)
    if paraguas:
        linea += " ☔ (llévate paraguas)"
    return {
        "max": tmax,
        "min": tmin,
        "prob_lluvia_max": prob_max,
        "tramos_lluvia": tramos,
        "descripcion": f"{emoji} {text}",
        "paraguas": paraguas,
        "linea": linea,
    }


def summarize(data, day: date):
    """Open-Meteo response -> brief weather."""
    iso = day.isoformat()
    daily, hourly = data["daily"], data["hourly"]
    if daily.get("time") != [iso] or not all(t.startswith(iso) for t in hourly.get("time", [])):
        raise StaleForecast(f"Open-Meteo devolvió datos de otra fecha (pedida {iso}, recibida {daily.get('time')})")
    probs = {int(t[11:13]): p for t, p in zip(hourly["time"], hourly["precipitation_probability"]) if p is not None}
    return build(
        daily["temperature_2m_max"][0],
        daily["temperature_2m_min"][0],
        daily["precipitation_probability_max"][0],
        probs,
        daily["weather_code"][0],
    )


def metno_code(symbol):
    """met.no symbol_code (e.g. 'lightrainshowers_day') -> WMO code; None if unknown."""
    base = symbol.split("_")[0]
    if "thunder" in base:
        return 95
    return METNO_TO_WMO.get(base)


def summarize_metno(data, day: date):
    """met.no locationforecast 2.0 response -> brief weather (times are UTC, converted to Madrid)."""
    temps, probs, amounts, symbols = [], {}, {}, []
    for entry in data["properties"]["timeseries"]:
        when = datetime.fromisoformat(entry["time"].replace("Z", "+00:00")).astimezone(MADRID)
        if when.date() != day:
            continue
        temps.append(entry["data"]["instant"]["details"]["air_temperature"])
        nxt = entry["data"].get("next_1_hours")
        if not nxt:  # shortcut: beyond ~2 days met.no is 6-hourly; rain hours come only from hourly steps
            continue
        details = nxt.get("details", {})
        amounts[when.hour] = details.get("precipitation_amount", 0) or 0
        if details.get("probability_of_precipitation") is not None:
            probs[when.hour] = details["probability_of_precipitation"]
        if when.hour in DAY_HOURS and "symbol_code" in nxt.get("summary", {}):
            symbols.append(nxt["summary"]["symbol_code"])
    if not temps:
        raise StaleForecast(f"met.no no tiene datos para {day.isoformat()}")
    if not probs:
        # met.no usually gives no rain probability outside the Nordics: estimate it from the
        # forecast amount, an hour with > 0.1 mm counts as rain (100 %), otherwise 0 %.
        probs = {h: 100 if mm > 0.1 else 0 for h, mm in amounts.items()}
    # shortcut: the day's description is the most common daytime symbol, not a weighted summary.
    code = metno_code(Counter(symbols).most_common(1)[0][0]) if symbols else None
    return build(max(temps), min(temps), max(probs.values(), default=0), probs, code)


class StaleForecast(ValueError):
    """The provider answered, but not for the requested day (never return another day's data)."""


def fetch_open_meteo(day: date):
    params = dict(PARAMS, start_date=day.isoformat(), end_date=day.isoformat())
    return summarize(net.get(API_URL, params).json(), day)


def fetch_metno(day: date):
    return summarize_metno(net.get(METNO_URL, METNO_PARAMS).json(), day)


PROVIDERS = (("open-meteo", fetch_open_meteo), ("met.no", fetch_metno))


def failure_cause(exc):
    """Doctor cause for a weather failure; 4xx other than 429 means the API changed."""
    return "servicio_caido" if isinstance(exc, StaleForecast) else net.cause(exc, client_error="formato_cambiado")


def get_weather(day: date):
    """Returns (weather, source): Open-Meteo, then met.no if it fails for any reason."""
    errors = []
    for name, fetch in PROVIDERS:
        try:
            return fetch(day), name
        except Exception as exc:
            errors.append(f"{name} ({failure_cause(exc)}): {type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors)) from None
