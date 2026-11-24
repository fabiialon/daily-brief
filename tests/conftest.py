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


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """No real waiting in any test: record the requested sleeps instead."""
    calls = []
    monkeypatch.setattr(time, "sleep", calls.append)
    return calls


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any test that forgets to fake requests.get fails instead of touching the network."""

    def blocked(*args, **kwargs):
        raise AssertionError("network access in tests")

    monkeypatch.setattr(requests, "get", blocked)


def source_of(url):
    return "open-meteo" if "open-meteo" in url else "met.no" if "met.no" in url else "blackboard"


@pytest.fixture
def fake_net(monkeypatch, ics_bytes, meteo, metno, sleeps):
    """Route requests.get by host to the fixtures.

    state["status"][source] = HTTP code to return for that source (e.g. 429);
    state["timeout"] = set of sources that raise a timeout;
    state["ics"] = body served as the Blackboard feed;
    state["json"][source] = JSON served by a weather provider.
    """
    state = {"status": {}, "timeout": set(), "calls": [], "ics": ics_bytes, "json": {"open-meteo": meteo, "met.no": metno}}

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
        if source in state["json"]:
            return FakeResponse(data=state["json"][source], url=url)
        return FakeResponse(content=state["ics"])

    monkeypatch.setenv("BLACKBOARD_ICS_URL", FAKE_URL)
    monkeypatch.setattr(requests, "get", fake_get)
    return state
