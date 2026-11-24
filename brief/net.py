"""HTTP GET shared by every source: retries with exponential backoff and failure classification."""
import time

import requests

USER_AGENT = "daily-brief/1.0 github.com/fabiialon/daily-brief"
RETRY_WAITS = (2, 4, 8)  # seconds between attempts: 1 try + 3 retries


def get(url, params=None, timeout=20):
    """GET that retries network errors, 429 and 5xx; raises the last error if all attempts fail."""
    for wait in RETRY_WAITS + (None,):
        try:
            resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError):
            if wait is None:
                raise
        else:
            if wait is None or (resp.status_code != 429 and resp.status_code < 500):
                resp.raise_for_status()
                return resp
        time.sleep(wait)


def cause(exc, client_error):
    """Doctor cause for a failed request. `client_error` is used for 4xx other than 429."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = exc.response.status_code
        if status == 429:
            return "limite_peticiones"
        return "servicio_caido" if status >= 500 else client_error
    if isinstance(exc, requests.Timeout):  # before ConnectionError: ConnectTimeout is both
        return "servicio_caido"
    if isinstance(exc, requests.ConnectionError):  # proxy refusal, DNS, connection refused, TLS
        return "dominio_bloqueado"
    return "formato_cambiado"
