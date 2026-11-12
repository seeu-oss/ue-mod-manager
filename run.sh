#!/bin/sh
cd "$(dirname "$0")" || exit 1
command -v python3 >/dev/null 2>&1 || { echo "需要 python3"; exit 1; }
exec python3 -m uemm --open
