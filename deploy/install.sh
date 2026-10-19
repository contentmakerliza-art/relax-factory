#!/usr/bin/env bash
# Installs or updates Relax Factory as a Docker container behind the server's
# existing Traefik. Nothing else on the server is changed.
# First run:  DOMAIN=relax.example.com bash deploy/install.sh
# Update:     bash deploy/install.sh
set -euo pipefail
cd "$(dirname "$0")"

git -C .. pull -q --ff-only || echo "Не удалось обновить код, ставлю текущую версию"

if [ ! -f .env ]; then
  PASS=$(head -c 24 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | cut -c1-16)
  if [ -z "${DOMAIN:-}" ]; then
    IP=$(curl -4 -s https://ifconfig.me)
    DOMAIN="${IP//./-}.sslip.io"
  fi
  cat > .env <<EOF
APP_PASSWORD=$PASS
RELAX_HOST=$DOMAIN
PROXY_NETWORK=${PROXY_NETWORK:-n8n_default}
CERT_RESOLVER=${CERT_RESOLVER:-mytlschallenge}
EOF
  chmod 600 .env
fi

mkdir -p /var/lib/relax-factory
docker compose up -d --build
git -C .. rev-parse --short HEAD > /var/lib/relax-factory/version

# pick up new versions from GitHub automatically (only this app is touched)
echo "*/5 * * * * root $(pwd)/autoupdate.sh >> /var/log/relax-factory-update.log 2>&1" > /etc/cron.d/relax-factory

set -a; . ./.env; set +a
echo
echo "Готово. Адрес: https://$RELAX_HOST"
echo "Логин любой, пароль: $APP_PASSWORD"
echo "Если адрес не открывается сразу, подождите 1-2 минуты: выпускается сертификат HTTPS."
