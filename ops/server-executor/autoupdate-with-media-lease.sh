#!/usr/bin/env bash
# Run by cron every 5 minutes: if the repository has new commits, pull them
# and rebuild the container. Waits while a video is rendering or Upload-Post
# is downloading one.
set -euo pipefail
cd "$(dirname "$0")/.."
DATA=/var/lib/relax-factory
exec 9>/tmp/relax-factory-update.lock
flock -n 9 || exit 0

git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && exit 0
runtime_changes=false
changed_paths=$(git diff --name-only HEAD..origin/main)
while IFS= read -r path; do
    case "$path" in
        docs/*|deploy/autoupdate.sh|"") ;;
        *) runtime_changes=true ;;
    esac
done <<< "$changed_paths"
if [ "$runtime_changes" = false ]; then
    git merge -q --ff-only origin/main
    git rev-parse --short HEAD > "$DATA/version"
    echo "$(date -Is) documentation updated; container preserved"
    exit 0
fi
[ -f "$DATA/busy" ] && exit 0
[ -f "$DATA/uploading" ] && exit 0  # Upload-Post is downloading a video by its link
# Server-side preview work happens outside the web app's busy marker.
# Hold its media lease throughout a real container update.
preview_lease=/opt/relax-codex/cabin-backlog/media-check.lock
if [ -f "$preview_lease" ]; then
    exec 8>"$preview_lease"
    flock -n 8 || exit 0
fi

echo "$(date -Is) updating $(git rev-parse --short HEAD) -> $(git rev-parse --short origin/main)"
git merge -q --ff-only origin/main
# leave one core and some memory for n8n and the rest of the server
cores=$(nproc); mem_gb=$(awk '/MemTotal/ {print int($2 / 1048576 + 0.5)}' /proc/meminfo)
if [ "$cores" -gt 2 ]; then export RELAX_CPUS=$((cores - 1)); fi
if [ "$mem_gb" -ge 6 ]; then export RELAX_MEM=$((mem_gb / 2))g RELAX_SWAP=$((mem_gb / 2 + 2))g; fi
cd deploy && docker compose up -d --build
git rev-parse --short HEAD > "$DATA/version"
