#!/usr/bin/env bash
set -euo pipefail
trainer_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x "$trainer_root/.venv/bin/python" ]]; then
    exec "$trainer_root/.venv/bin/python" "$trainer_root/scripts/train_stroke_classifier.py" "$@"
fi
exec python3 "$trainer_root/scripts/train_stroke_classifier.py" "$@"
