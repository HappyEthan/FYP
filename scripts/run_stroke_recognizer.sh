#!/usr/bin/env bash
set -euo pipefail
recognizer_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x "$recognizer_root/.venv/bin/python" ]]; then
    exec "$recognizer_root/.venv/bin/python" "$recognizer_root/scripts/recognize_strokes_live.py" "$@"
fi
exec python3 "$recognizer_root/scripts/recognize_strokes_live.py" "$@"
