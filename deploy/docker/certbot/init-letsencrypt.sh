#!/bin/sh
# One-time bootstrap for the Let's Encrypt cert on a FRESH server — run
# once from the repo root: `sh deploy/docker/certbot/init-letsencrypt.sh`.
#
# Why this dance and not just `docker compose up -d nginx`: nginx.conf's
# 443 server block points at
# /etc/letsencrypt/live/clinicnet.stom.asia/{fullchain,privkey}.pem, which
# doesn't exist yet on a fresh server — nginx would refuse to even start.
# So: fake a self-signed cert at that exact path so nginx *can* start and
# serve the ACME HTTP-01 challenge on port 80, request the real cert
# through that running nginx, then discard the fake and reload with the
# real one. Standard pattern for nginx+certbot in docker-compose
# (this is the well-known wmnnd/certbot-nginx recipe, adapted to one
# domain and this repo's compose file).
set -e

DOMAIN=clinicnet.stom.asia
DATA_PATH=./deploy/docker/certbot
EMAIL="${CERTBOT_EMAIL:-}"   # set CERTBOT_EMAIL=you@example.com for renewal notices; optional otherwise

if [ -z "$EMAIL" ]; then
  EMAIL_ARG="--register-unsafely-without-email"
else
  EMAIL_ARG="--email $EMAIL"
fi

echo "### Пишу рекомендованные TLS-параметры Let's Encrypt (options-ssl-nginx.conf) ..."
# Зашито прямо в скрипт, а не скачано с GitHub: пути certbot-репозитория,
# откуда раньше качался этот файл, перестали существовать (curl молча
# получал "404: Not Found" и клал этот текст в конфиг — nginx с ним не
# стартовал). Содержимое ниже — стандартный certbot-nginx intermediate-
# профиль (TLS 1.2/1.3), одинаковый у всех, кто ставил certbot руками.
mkdir -p "$DATA_PATH/conf"
cat > "$DATA_PATH/conf/options-ssl-nginx.conf" <<'CONF'
ssl_session_cache shared:le_nginx_SSL:10m;
ssl_session_timeout 1440m;
ssl_session_tickets off;

ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers off;

ssl_ciphers "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384";
CONF

echo "### Генерирую ssl-dhparams.pem (2048 бит, локально, без внешних зависимостей) ..."
# Без проверки "уже существует": скрипт может перезапускаться после
# сбоя (как только что — старая версия оставляла тут битый файл с
# "404: Not Found"), так что каждый повторный запуск просто пишет заново.
docker compose run --rm --entrypoint "openssl dhparam -out /etc/letsencrypt/ssl-dhparams.pem 2048" certbot

echo "### Создаю временный self-signed сертификат, чтобы nginx вообще смог стартовать ..."
CERT_PATH="/etc/letsencrypt/live/$DOMAIN"
mkdir -p "$DATA_PATH/conf/live/$DOMAIN"
docker compose run --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout '$CERT_PATH/privkey.pem' \
    -out '$CERT_PATH/fullchain.pem' \
    -subj '/CN=localhost'" certbot

echo "### Стартую nginx с временным сертификатом ..."
docker compose up -d nginx

echo "### Удаляю временный сертификат ..."
# Один `rm -rf` с тремя путями, не три через `&&` — --entrypoint не идёт
# через шелл (docker compose разбивает строку на argv напрямую), так что
# `&&` здесь был бы просто лишним буквальным аргументом для rm, а не
# оператором шелла.
docker compose run --rm --entrypoint "rm -rf /etc/letsencrypt/live/$DOMAIN /etc/letsencrypt/archive/$DOMAIN /etc/letsencrypt/renewal/$DOMAIN.conf" certbot

echo "### Запрашиваю настоящий сертификат у Let's Encrypt ..."
docker compose run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $EMAIL_ARG \
    -d $DOMAIN \
    --rsa-key-size 4096 \
    --agree-tos \
    --non-interactive" certbot

echo "### Перезагружаю nginx с настоящим сертификатом ..."
docker compose exec nginx nginx -s reload

echo "### Готово. Обновление сертификата (раз в ~90 дней) — см. раздел про cron/systemd-timer в docs/DEPLOY-DOCKER.md."
