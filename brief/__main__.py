"""CLI: python -m brief [--date YYYY-MM-DD] -> JSON on stdout, always exit 0.

`--doctor` checks every source instead and exits 1 if any of them failed.
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

from brief import blackboard, doctor, weather


def build(day: date):
    out = {
        "fecha": day.isoformat(),
        "manana": (day + timedelta(days=1)).isoformat(),
        "blackboard": None,
        "clima": None,
        "clima_fuente": None,
        "errores": [],
    }
    for key, fetch in (("blackboard", blackboard.get_events), ("clima", weather.get_weather)):
        try:
            if key == "clima":
                out["clima"], out["clima_fuente"] = fetch(day)
            else:
                out[key] = fetch(day)
        except Exception as exc:  # one source failing must not break the brief
            msg = f"{type(exc).__name__}: {exc}" if not isinstance(exc, blackboard.SourceError) else str(exc)
            out["errores"].append({"fuente": key, "mensaje": blackboard.sanitize(msg, os.environ.get(blackboard.ENV_VAR))})
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m brief")
    parser.add_argument("--date", type=date.fromisoformat, help="YYYY-MM-DD (por defecto: hoy en Madrid)")
    parser.add_argument("--doctor", action="store_true", help="comprueba cada fuente y clasifica los fallos")
    args = parser.parse_args(argv)
    day = args.date or datetime.now(blackboard.MADRID).date()
    sys.stdout.reconfigure(encoding="utf-8")
    result = doctor.run(day) if args.doctor else build(day)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if args.doctor and not result["ok"] else 0


if __name__ == "__main__":
    sys.exit(main())
