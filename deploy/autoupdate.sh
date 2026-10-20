#!/usr/bin/env bash
# Run by cron every 5 minutes: if the repository has new commits, pull them
# and rebuild the container. Waits while a video is rendering.
set -euo pipefail
cd "$(dirname "$0")/.."
DATA=/var/lib/relax-factory
exec 9>/tmp/relax-factory-update.lock
flock -n 9 || exit 0

git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && exit 0
[ -f "$DATA/busy" ] && exit 0

echo "$(date -Is) updating $(git rev-parse --short HEAD) -> $(git rev-parse --short origin/main)"
git merge -q --ff-only origin/main
# leave one core and some memory for n8n and the rest of the server
cores=$(nproc); mem_gb=$(awk '/MemTotal/ {print int($2 / 1048576 + 0.5)}' /proc/meminfo)
if [ "$cores" -gt 2 ]; then export RELAX_CPUS=$((cores - 1)); fi
if [ "$mem_gb" -ge 6 ]; then export RELAX_MEM=$((mem_gb / 2))g RELAX_SWAP=$((mem_gb / 2 + 2))g; fi
cd deploy && docker compose up -d --build
git rev-parse --short HEAD > "$DATA/version"
