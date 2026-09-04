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

echo "### Скачиваю рекомендованные TLS-параметры Let's Encrypt (options-ssl-nginx.conf, ssl-dhparams.pem) ..."
mkdir -p "$DATA_PATH/conf"
curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf > "$DATA_PATH/conf/options-ssl-nginx.conf"
curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot/certbot/ssl-dhparams.pem > "$DATA_PATH/conf/ssl-dhparams.pem"

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
docker compose run --rm --entrypoint "\
  rm -rf /etc/letsencrypt/live/$DOMAIN && \
  rm -rf /etc/letsencrypt/archive/$DOMAIN && \
  rm -rf /etc/letsencrypt/renewal/$DOMAIN.conf" certbot

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
