#!/usr/bin/env bash
set -euo pipefail
script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Error: Python 3.9+ is required. Install python3 and try again.' >&2
  exit 1
fi
exec python3 "$script_dir/export.py" "$@"
