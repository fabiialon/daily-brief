"""Turns the doctor report + pytest result into the workflow's decision.

Usage in CI: python -m brief.health DOCTOR_JSON TESTS_OUTCOME ISSUE_BODY_FILE
Writes ok / needs_user / needs_code / issue_title to $GITHUB_OUTPUT and the issue body to a file.
"""
import json
import os
import sys

from brief.doctor import CODE_CAUSES, USER_CAUSES

TITLES = {
    "enlace_caducado": "Blackboard: el enlace del calendario ha caducado",
    "dominio_bloqueado": "No se puede conectar con una fuente del resumen",
    "falta_configuracion": "Falta el secreto BLACKBOARD_ICS_URL",
}


def plan(report, tests_ok):
    """{ok, needs_user, needs_code, issue_title, issue_body} for a doctor report (None if it crashed)."""
    if report is None:
        return {"ok": False, "needs_user": False, "needs_code": True, "issue_title": "", "issue_body": ""}
    fallos = [f for f in report.get("fuentes", []) if f["estado"] == "fallo"]
    user = [f for f in fallos if f["causa"] in USER_CAUSES]
    body = ""
    if user:
        lines = ["La vigilancia diaria de daily-brief ha encontrado algo que solo tú puedes arreglar.", ""]
        for f in user:
            lines += [f"### {f['fuente']}: {f['causa']}", "", f["accion_usuario"], ""]
            if f.get("detalle"):
                lines += [f"Detalle técnico: `{f['detalle']}`", ""]
        lines.append("Cuando lo arregles, lanza `gh workflow run health.yml`: si sale en verde, esta issue se cierra sola.")
        body = "\n".join(lines)
    return {
        "ok": tests_ok and not fallos,
        "needs_user": bool(user),
        "needs_code": not tests_ok or any(f["causa"] in CODE_CAUSES for f in fallos),
        "issue_title": TITLES[user[0]["causa"]] if user else "",
        "issue_body": body,
    }


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def main(argv=None):
    report_path, tests_outcome, body_path = argv or sys.argv[1:]
    result = plan(load(report_path), tests_outcome == "success")
    with open(body_path, "w", encoding="utf-8") as fh:
        fh.write(result.pop("issue_body"))
    lines = [f"{k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in result.items()]
    print("\n".join(lines))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
