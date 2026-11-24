import json
from pathlib import Path

import pytest
import requests

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_URL = "https://example.invalid/webapps/calendar/calendarFeed/FAKEID123SECRET/learn.ics"


class FakeResponse:
    def __init__(self, status=200, content=b"", data=None):
        self.status_code, self.content, self._data = status, content, data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error for url: {FAKE_URL}", response=self)


@pytest.fixture
def ics_bytes():
    return (FIXTURES / "sample.ics").read_bytes()


@pytest.fixture
def meteo():
    return json.loads((FIXTURES / "open_meteo.json").read_text(encoding="utf-8"))


@pytest.fixture
def fake_net(monkeypatch, ics_bytes, meteo):
    """Route requests.get: Open-Meteo -> fixture JSON; anything else -> sample.ics. Set `fail` to break a source."""
    state = {"fail": None, "calls": []}

    def fake_get(url, params=None, timeout=None):
        state["calls"].append(url)
        source = "clima" if "open-meteo" in url else "blackboard"
        if state["fail"] == source:
            raise requests.Timeout(f"HTTPSConnectionPool: Read timed out. (url: {url})")
        if source == "clima":
            assert params["start_date"] == params["end_date"]
            return FakeResponse(data=meteo)
        return FakeResponse(content=ics_bytes)

    monkeypatch.setenv("BLACKBOARD_ICS_URL", FAKE_URL)
    monkeypatch.setattr(requests, "get", fake_get)
    return state
