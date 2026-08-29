# Деплой ClinicNet — `clinicnet.stom.asia`

Docker Compose: Django (gunicorn) + Postgres 16 + nginx + Let's Encrypt (certbot).
Выполняется на сервере (`46.149.68.65`), под root.

## 0. DNS

В панели DNS-провайдера домена `stom.asia` добавить:

```
A    clinicnet.stom.asia    →    46.149.68.65
```

Подождать, пока распространится (обычно несколько минут, проверить: `dig +short clinicnet.stom.asia`).

## 1. Docker (если ещё не установлен)

```bash
curl -fsSL https://get.docker.com | sh
```

## 2. Клонировать репозиторий

```bash
cd /opt
git clone https://github.com/Akmalidin/ClinicNet.git
cd ClinicNet
git checkout main   # после того как PR'ы Фазы 1/2 смёржены — см. ниже
```

> Пока PR'ы не смёржены в `main`, можно временно выкатить с ветки
> `claude/phase2-emk-referrals-models` (`git checkout claude/phase2-emk-referrals-models`)
> — в ней уже весь код Фазы 1+2. После мержа — переключиться на `main` и
> обновлять через `git pull`.

## 3. `.env`

```bash
cp deploy/.env.production.example .env
```

Заполнить `.env` (сгенерированные значения — вставить как есть, если не хотите свои):

```
SECRET_KEY=CdzITDmCC5EhbioyELTB37veflZYUyjbPEdd2fBclLLx8NR2uItr7eoY8h5R
DB_PASSWORD=Qkowm1CxKDshRQhWyGEDfEOxCWlYXLBT
```

(остальные поля `.env.production.example` — `DEBUG=False`, `ALLOWED_HOSTS`,
`DB_NAME`, `DB_USER` — уже правильные, не трогать).

## 4. Первый запуск (без SSL — только HTTP, для получения сертификата)

```bash
cp deploy/nginx/clinicnet-http.conf.template deploy/nginx/clinicnet.conf
docker compose -f docker-compose.prod.yml up -d --build
```

Проверить, что поднялось: `curl -I http://clinicnet.stom.asia/admin/` — должен
ответить nginx (302/200/404 — не важно что именно, важно что не connection
refused).

## 5. Получить сертификат Let's Encrypt

```bash
docker compose -f docker-compose.prod.yml run --rm certbot \
  certonly --webroot -w /var/www/certbot \
  -d clinicnet.stom.asia \
  --email <ваш-email> --agree-tos --no-eff-email
```

## 6. Переключиться на HTTPS

```bash
cp deploy/nginx/clinicnet-ssl.conf.template deploy/nginx/clinicnet.conf
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

Проверить: `curl -I https://clinicnet.stom.asia/admin/` — должен быть 200/302
с валидным сертификатом.

## 7. Создать первую сеть клиник (тенант)

`entrypoint.sh` уже применил публичные миграции (`migrate_schemas --shared`)
при старте контейнера `web`. Дальше — создать саму сеть:

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py create_tenant \
  --schema_name=clinicnet --name="ClinicNet" \
  --domain-domain=clinicnet.stom.asia --domain-is_primary=True --noinput

docker compose -f docker-compose.prod.yml exec web python manage.py tenant_command \
  seed_rbac --schema=clinicnet
```

## 8. Создать первого пользователя (сеть-администратора)

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py tenant_command \
  shell --schema=clinicnet
```

```python
from apps.accounts.models import User, Role, UserRole, BranchScope
u = User.objects.create_superuser(username="admin", password="<придумать пароль>")
role = Role.objects.get(codename="network-admin")
UserRole.objects.create(user=u, role=role, branch_scope=BranchScope.ALL)
exit()
```

## Дальнейшие обновления

```bash
cd /opt/ClinicNet
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

`entrypoint.sh` сам прогонит новые миграции (`migrate_schemas --shared`) при
рестарте `web`. Миграции самих тенант-схем (`migrate_schemas --schema=<...>`
для не-shared приложений) — выполнять вручную после апдейта с миграциями:

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py migrate_schemas --schema=clinicnet
```

## Восстановление сертификата / диагностика

- Логи: `docker compose -f docker-compose.prod.yml logs -f web` / `nginx` / `certbot`
- certbot продлевает сертификат автоматически (контейнер `certbot` крутит
  `certbot renew` раз в 12 часов) — вручную дёргать не нужно.
