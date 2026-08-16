#!/bin/sh
set -eu

mode="${1:-daemon}"

case "$mode" in
    daemon)
        exec python -m monitorUbi.daemon
        ;;
    web)
        export MONITORUBI_DISABLE_SYSTEMD=1
        export MONITORUBI_TUI_MODE=observer
        exec textual serve \
            --host "${MONITORUBI_WEB_HOST:-0.0.0.0}" \
            --port "${MONITORUBI_WEB_PORT:-8080}" \
            --title monitorUbi \
            --command "python -m monitorUbi"
        ;;
    tui)
        export MONITORUBI_DISABLE_SYSTEMD=1
        shift
        exec python -m monitorUbi "$@"
        ;;
    *)
        exec "$@"
        ;;
esac
