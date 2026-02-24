#!/bin/bash
# Shared helpers for Charmed Apache Kafka tutorial spread tests.
#
# Source this file at the top of every task execute/prepare block:
#   . "$SPREAD_PATH/tests/tutorial/helpers.sh"

# ---------------------------------------------------------------------------
# juju_wait – poll until every Juju unit in the model is active/idle.
#
# Usage:
#   juju_wait [--timeout SECONDS] [--interval SECONDS]
#
# Defaults:
#   --timeout  600   (10 minutes)
#   --interval  30   (check every 30 seconds)
#
# Returns 0 when all units are active/idle, 1 on timeout.
# ---------------------------------------------------------------------------
juju_wait() {
    local timeout=600
    local interval=30

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --timeout)  timeout="$2";  shift 2 ;;
            --interval) interval="$2"; shift 2 ;;
            *) echo "juju_wait: unknown option: $1" >&2; return 1 ;;
        esac
    done

    local elapsed=0
    echo "Waiting for all Juju units to be active/idle (timeout=${timeout}s, poll=${interval}s)…"

    while [[ "$elapsed" -lt "$timeout" ]]; do
        local not_ready
        not_ready=$(
            juju status --format=json 2>/dev/null | python3 - <<'PYEOF'
import json, sys
try:
    data = json.load(sys.stdin)
    not_ready = 0
    for app in data.get("applications", {}).values():
        for unit in app.get("units", {}).values():
            ws = unit.get("workload-status", {}).get("current", "")
            js = unit.get("juju-status",    {}).get("current", "")
            if ws != "active" or js != "idle":
                not_ready += 1
    print(not_ready)
except Exception:
    print("error")
PYEOF
        )

        if [[ "$not_ready" == "0" ]]; then
            echo "All units active/idle after ${elapsed}s."
            juju status
            return 0
        fi

        echo "[${elapsed}s elapsed] ${not_ready} unit(s) not in active/idle – rechecking in ${interval}s…"
        sleep "$interval"
        elapsed=$(( elapsed + interval ))
    done

    echo "Timed out after ${timeout}s. Final status:"
    juju status
    return 1
}
