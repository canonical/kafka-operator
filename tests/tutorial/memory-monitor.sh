#!/bin/bash
# Record peak RAM use inside the tutorial test VM, per stage and overall.
#
# Usage:
#   memory-monitor.sh start          start the background sampler (systemd unit)
#   memory-monitor.sh mark <stage>   set the stage that new samples belong to
#   memory-monitor.sh stop           stop the background sampler
#   memory-monitor.sh report         print the report and save it to report.txt
#   memory-monitor.sh sample         sampling loop (run by the systemd unit)
#
# Used RAM is MemTotal - MemAvailable from /proc/meminfo, for the whole VM.

set -euo pipefail

STATE_DIR="${TUTORIAL_MEMORY_DIR:-/var/tmp/tutorial-memory}"
INTERVAL="${TUTORIAL_MEMORY_INTERVAL:-10}"
UNIT="tutorial-memory-monitor"
SCRIPT="$(readlink -f "$0")"

used_mib() {
    awk '/^MemTotal:/ {t = $2} /^MemAvailable:/ {a = $2} END {printf "%d\n", (t - a) / 1024}' /proc/meminfo
}

total_mib() {
    awk '/^MemTotal:/ {printf "%d\n", $2 / 1024}' /proc/meminfo
}

format_mib() {
    awk -v m="$1" 'BEGIN {printf "%d MiB (%.1f GiB)", m, m / 1024}'
}

update_peak() {
    local file="$1" value="$2" details="${3:-}" current=0
    if [[ -f "$file" ]]; then
        read -r current _ < "$file"
    fi
    if (( value > current )); then
        echo "$value $details" > "$file.tmp"
        mv "$file.tmp" "$file"
    fi
}

cmd_start() {
    mkdir -p "$STATE_DIR"
    rm -f "$STATE_DIR"/peak-* "$STATE_DIR/report.txt"
    echo setup > "$STATE_DIR/current-stage"
    echo setup > "$STATE_DIR/order"
    echo "$INTERVAL" > "$STATE_DIR/interval"
    systemctl stop "$UNIT" 2>/dev/null || true
    systemctl reset-failed "$UNIT" 2>/dev/null || true
    systemd-run --unit="$UNIT" --quiet \
        --setenv=TUTORIAL_MEMORY_DIR="$STATE_DIR" \
        --setenv=TUTORIAL_MEMORY_INTERVAL="$INTERVAL" \
        /bin/bash "$SCRIPT" sample
}

cmd_sample() {
    local used stage now
    while true; do
        used=$(used_mib)
        stage=$(cat "$STATE_DIR/current-stage" 2>/dev/null || echo setup)
        now=$(date -u +%H:%M:%S)
        update_peak "$STATE_DIR/peak-overall" "$used" "$stage $now"
        update_peak "$STATE_DIR/peak-stage-$stage" "$used"
        sleep "$INTERVAL"
    done
}

cmd_mark() {
    local stage="${1:-}"
    stage="${stage##*/}"
    if [[ -z "$stage" ]]; then
        echo "usage: $0 mark <stage>" >&2
        exit 1
    fi
    mkdir -p "$STATE_DIR"
    echo "$stage" > "$STATE_DIR/current-stage"
    if ! grep -qx "$stage" "$STATE_DIR/order" 2>/dev/null; then
        echo "$stage" >> "$STATE_DIR/order"
    fi
}

cmd_stop() {
    systemctl stop "$UNIT" 2>/dev/null || true
}

cmd_report() {
    local interval total stage value peak peak_stage peak_time
    mkdir -p "$STATE_DIR"
    interval=$(cat "$STATE_DIR/interval" 2>/dev/null || echo "$INTERVAL")
    total=$(total_mib)
    {
        echo "=== Tutorial memory report (sampled every ${interval}s) ==="
        printf '%-40s %s\n' "Stage" "Peak RAM used"
        if [[ -f "$STATE_DIR/order" ]]; then
            while read -r stage; do
                [[ -f "$STATE_DIR/peak-stage-$stage" ]] || continue
                read -r value _ < "$STATE_DIR/peak-stage-$stage"
                printf '%-40s %s\n' "$stage" "$(format_mib "$value")"
            done < "$STATE_DIR/order"
        fi
        if [[ -f "$STATE_DIR/peak-overall" ]]; then
            read -r peak peak_stage peak_time < "$STATE_DIR/peak-overall"
            echo "Overall peak: $(format_mib "$peak") during stage '$peak_stage' at $peak_time UTC"
            echo "VM memory:    $(format_mib "$total")"
            if (( peak * 100 >= total * 95 )); then
                echo "WARNING: the peak is at least 95% of the VM memory, so the VM size capped it."
                echo "Raise SPREAD_VM_MEM and re-run to measure the real requirement."
            fi
        else
            echo "No samples recorded."
        fi
    } | tee "$STATE_DIR/report.txt"
}

case "${1:-}" in
    start)  cmd_start ;;
    sample) cmd_sample ;;
    mark)   cmd_mark "${2:-}" ;;
    stop)   cmd_stop ;;
    report) cmd_report ;;
    *)
        echo "usage: $0 {start|mark <stage>|stop|report|sample}" >&2
        exit 1
        ;;
esac
