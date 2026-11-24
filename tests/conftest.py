import json
import time
from pathlib import Path

import pytest
import requests

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_URL = "https://example.invalid/webapps/calendar/calendarFeed/FAKEID123SECRET/learn.ics"


class FakeResponse:
    def __init__(self, status=200, content=b"", data=None, url=FAKE_URL):
        self.status_code, self.content, self._data, self.url = status, content, data, url

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error for url: {self.url}", response=self)


@pytest.fixture
def ics_bytes():
    return (FIXTURES / "sample.ics").read_bytes()


@pytest.fixture
def meteo():
    return json.loads((FIXTURES / "open_meteo.json").read_text(encoding="utf-8"))


@pytest.fixture
def metno():
    return json.loads((FIXTURES / "metno.json").read_text(encoding="utf-8"))


@pytest.fixture
def sleeps(monkeypatch):
    """No real waiting: record the requested sleeps instead."""
    calls = []
    monkeypatch.setattr(time, "sleep", calls.append)
    return calls


def source_of(url):
    return "open-meteo" if "open-meteo" in url else "met.no" if "met.no" in url else "blackboard"


@pytest.fixture
def fake_net(monkeypatch, ics_bytes, meteo, metno, sleeps):
    """Route requests.get by host to the fixtures.

    state["status"][source] = HTTP code to return for that source (e.g. 429);
    state["timeout"] = set of sources that raise a timeout.
    """
    state = {"status": {}, "timeout": set(), "calls": []}

    def fake_get(url, params=None, headers=None, timeout=None):
        source = source_of(url)
        state["calls"].append((source, headers))
        if source in state["timeout"]:
            raise requests.Timeout(f"HTTPSConnectionPool: Read timed out. (url: {url})")
        status = state["status"].get(source, 200)
        if status != 200:
            return FakeResponse(status=status, url=url)
        if source == "open-meteo":
            assert params["start_date"] == params["end_date"]
            return FakeResponse(data=meteo, url=url)
        if source == "met.no":
            return FakeResponse(data=metno, url=url)
        return FakeResponse(content=ics_bytes)

    monkeypatch.setenv("BLACKBOARD_ICS_URL", FAKE_URL)
    monkeypatch.setattr(requests, "get", fake_get)
    return state
