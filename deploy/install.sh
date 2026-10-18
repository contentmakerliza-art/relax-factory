#!/usr/bin/env bash
# Installs or updates Relax Factory on an Ubuntu/Debian server.
# Usage (as root):  REPO=https://github.com/<owner>/<repo>.git bash install.sh
# Re-running it updates the code and keeps the password and rendered videos.
set -euo pipefail

REPO="${REPO:?set REPO to the git URL}"
APP_DIR=/opt/relax-factory
DATA_DIR=/var/lib/relax-factory
ENV_FILE=/etc/relax-factory.env

apt-get update -qq
apt-get install -y -qq ffmpeg git python3-venv curl debian-keyring debian-archive-keyring apt-transport-https >/dev/null

id relax >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin relax
mkdir -p "$DATA_DIR" && chown relax:relax "$DATA_DIR"

if [ -d "$APP_DIR/.git" ]; then git -C "$APP_DIR" pull -q; else git clone -q "$REPO" "$APP_DIR"; fi
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

if [ ! -f "$ENV_FILE" ]; then
  PASS=$(tr -dc 'a-zA-Z0-9' </dev/urandom | head -c 16)
  printf 'APP_PASSWORD=%s\nAPP_DATA=%s\n' "$PASS" "$DATA_DIR" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

cat > /etc/systemd/system/relax-factory.service <<EOF
[Unit]
Description=Relax Factory
After=network.target

[Service]
User=relax
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
Restart=always
Nice=10

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now relax-factory >/dev/null
systemctl restart relax-factory

# HTTPS without buying a domain: Caddy + <ip>.sslip.io
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi
IP=$(curl -4 -s https://ifconfig.me)
HOST="${DOMAIN:-${IP//./-}.sslip.io}"
cat > /etc/caddy/Caddyfile <<EOF
$HOST {
    request_body {
        max_size 20GB
    }
    reverse_proxy 127.0.0.1:8000
}
EOF
systemctl reload caddy || systemctl restart caddy

echo
echo "Готово. Адрес: https://$HOST"
echo "Пароль (логин любой): $(grep APP_PASSWORD "$ENV_FILE" | cut -d= -f2)"
