#!/usr/bin/env bash
# Chrome on the server for uploading videos to YouTube Studio.
#   bash /opt/relax-factory/deploy/browser.sh start
#   bash /opt/relax-factory/deploy/browser.sh stop
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a
case "${1:-start}" in
  start)
    if [ -f /var/lib/relax-factory/busy ]; then
      echo "Сейчас идёт рендер. Запустите браузер, когда он закончится: памяти на двоих не хватит."
      exit 1
    fi
    BROWSER_AUTH="relax:$(openssl passwd -apr1 "$APP_PASSWORD")"
    export BROWSER_AUTH
    mkdir -p /var/lib/relax-browser
    chown 1000:1000 /var/lib/relax-browser
    docker compose -f browser.yml up -d
    echo
    echo "Браузер: https://browser.$RELAX_HOST"
    echo "Логин relax, пароль тот же, что у приложения."
    echo "Видео в окне выбора файла: папка /videos."
    echo "После загрузки остановите: bash $(pwd)/browser.sh stop"
    ;;
  stop)
    BROWSER_AUTH=x docker compose -f browser.yml down
    echo "Браузер остановлен."
    ;;
  *)
    echo "Использование: browser.sh start | stop"; exit 1 ;;
esac
