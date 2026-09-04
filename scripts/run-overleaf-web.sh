#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -n "${CHATSITE_ENV_FILE:-}" && -f "${CHATSITE_ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${CHATSITE_ENV_FILE}"
  set +a
fi

CHATOL_SRC="${CHATOL_SRC:-/home/zhihong/Playground/core/ChatOL/src}"
export PYTHONPATH="${ROOT}/src:${CHATOL_SRC}${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 -m chatsite.overleaf_web "$@"
