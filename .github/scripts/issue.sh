#!/usr/bin/env bash
# Keeps at most ONE open issue labelled necesita-fabian. Needs GH_TOKEN and GH_REPO.
#   issue.sh upsert TITLE BODY_FILE   -> opens it, or adds a dated comment to the open one
#   issue.sh close                    -> closes every open one with the comment "Resuelto"
set -euo pipefail
LABEL=necesita-fabian
gh label create "$LABEL" --color D93F0B --description "daily-brief necesita que Fabián haga algo" >/dev/null 2>&1 || true
open_issues=$(gh issue list --label "$LABEL" --state open --limit 20 --json number --jq '.[].number')

case "$1" in
  upsert)
    existing=$(echo "$open_issues" | head -n 1)
    if [ -n "$existing" ]; then
      { echo "**$2** ($(date -u +%F))"; echo; cat "$3"; } | gh issue comment "$existing" --body-file -
    else
      gh issue create --title "$2" --label "$LABEL" --body-file "$3"
    fi
    ;;
  close)
    for n in $open_issues; do
      gh issue close "$n" --comment "Resuelto"
    done
    ;;
  *)
    echo "uso: issue.sh upsert TITULO ARCHIVO | issue.sh close" >&2
    exit 2
    ;;
esac
