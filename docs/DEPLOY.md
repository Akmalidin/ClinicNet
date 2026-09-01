# Деплой ClinicNet — `clinicnet.stom.asia`

Сервер `46.149.68.65` — **общий продовый хост**, на нём уже живут SADAF
(`sadaf.service`, `/var/www/sadaf`), AutoParts ERP (`erp_gunicorn.service`) и
CRM (`gunicorn.service`) за одним nginx и одним кластером Postgres
(`postgresql@16-main`). Docker на сервере не установлен и не используется —
ClinicNet разворачивается **тем же способом, что и соседи**: systemd-юнит
с gunicorn на своём порту + свой vhost в существующем nginx + своя база в
существующем кластере Postgres. Ничего из уже работающего не трогаем,
не останавливаем, не перезапускаем.

Занятые порты (не использовать): `8001` (CRM), `8021` (SADAF). ClinicNet —
`8041`.

## 1. DNS

В панели DNS-провайдера `timeweb.cloud` для `stom.asia` добавить:

```
A    clinicnet.stom.asia    →    46.149.68.65
```

Сертификат отдельно выпускать не нужно — уже есть wildcard-сертификат
`stom.asia` / `*.stom.asia` (`/etc/letsencrypt/live/stom.asia/`), он
покрывает `clinicnet.stom.asia`.

## 2. База данных (в существующем кластере, отдельная от sadaf/erp/crm)

```bash
sudo -u postgres psql -c "CREATE USER clinicnet WITH PASSWORD 'Qkowm1CxKDshRQhWyGEDfEOxCWlYXLBT';"
sudo -u postgres psql -c "CREATE DATABASE clinicnet OWNER clinicnet;"
```

## 3. Приложение

```bash
mkdir -p /var/www/clinicnet
chown www-data:www-data /var/www/clinicnet
cd /var/www/clinicnet
sudo -u www-data git clone https://github.com/Akmalidin/ClinicNet.git .
sudo -u www-data git checkout claude/phase2-emk-referrals-models   # до мержа PR в main
sudo -u www-data python3 -m venv venv
sudo -u www-data venv/bin/pip install -r requirements.txt
```

`.env` (владелец `www-data`, права `600` — секреты):

```bash
sudo -u www-data tee /var/www/clinicnet/.env > /dev/null <<'EOF'
DEBUG=False
SECRET_KEY=CdzITDmCC5EhbioyELTB37veflZYUyjbPEdd2fBclLLx8NR2uItr7eoY8h5R
ALLOWED_HOSTS=clinicnet.stom.asia
DB_NAME=clinicnet
DB_USER=clinicnet
DB_PASSWORD=Qkowm1CxKDshRQhWyGEDfEOxCWlYXLBT
DB_HOST=127.0.0.1
DB_PORT=5432
EOF
chmod 600 /var/www/clinicnet/.env
```

Миграции и создание сети клиник:

```bash
cd /var/www/clinicnet
sudo -u www-data venv/bin/python manage.py collectstatic --noinput
sudo -u www-data venv/bin/python manage.py migrate_schemas --shared --noinput

sudo -u www-data venv/bin/python manage.py create_tenant \
  --schema_name=clinicnet --name="ClinicNet" \
  --domain-domain=clinicnet.stom.asia --domain-is_primary=True --noinput

sudo -u www-data venv/bin/python manage.py tenant_command seed_rbac --schema=clinicnet
```

## 4. systemd

```bash
cp deploy/systemd/clinicnet.service /etc/systemd/system/clinicnet.service
systemctl daemon-reload
systemctl enable --now clinicnet
systemctl status clinicnet   # должен быть active (running)
```

## 5. nginx (новый vhost, существующие не трогаем)

```bash
cp deploy/nginx/clinicnet-stom-asia /etc/nginx/sites-available/clinicnet-stom-asia
ln -s /etc/nginx/sites-available/clinicnet-stom-asia /etc/nginx/sites-enabled/clinicnet-stom-asia
nginx -t   # обязательно проверить перед reload
systemctl reload nginx   # reload, не restart — не рвёт соединения к sadaf/erp/crm
```

`server_name clinicnet.stom.asia` (точное совпадение) в новом vhost
приоритетнее `*.stom.asia` (wildcard) в `sites-available/stom-asia` — запрос
уйдёт в ClinicNet, SADAF не заденет.

Проверить: `curl -I https://clinicnet.stom.asia/admin/` — ожидается `200`
или `302` с валидным сертификатом.

## 6. Первый пользователь (администратор сети)

```bash
cd /var/www/clinicnet
sudo -u www-data venv/bin/python manage.py tenant_command shell --schema=clinicnet
```

```python
from apps.accounts.models import User, Role, UserRole, BranchScope
u = User.objects.create_superuser(username="admin", password="<придумать пароль>")
role = Role.objects.get(codename="network-admin")
UserRole.objects.create(user=u, role=role, branch_scope=BranchScope.ALL)
exit()
```

## 7. AI-триаж (Фаза 5, под-модуль 2) — отдельный сервис

`triage_service/` — не Django-приложение, отдельный FastAPI-процесс, своё
окружение, свой systemd-юнит. Подробности — `triage_service/README.md` и
`docs/PHASE5-TRIAGE-DESIGN.md`.

**Сервисный аккаунт бота** (роль `triage-bot`, только `triage.ingest`,
`branch_scope=ALL` — бот не привязан к одному филиалу):

```bash
cd /var/www/clinicnet
sudo -u www-data venv/bin/python manage.py tenant_command shell --schema=clinicnet
```

```python
from apps.accounts.models import User, Role, UserRole, BranchScope
bot = User.objects.create_user(username="triage_bot_service", password="<сгенерировать длинный пароль>")
role = Role.objects.get(codename="triage-bot")
UserRole.objects.create(user=bot, role=role, branch_scope=BranchScope.ALL)
exit()
```

**Установка и запуск** (отдельное окружение — `requirements.txt` сервиса
короче и не пересекается с Django-зависимостями):

```bash
cd /var/www/clinicnet/triage_service
sudo -u www-data python3 -m venv /var/www/clinicnet/triage_venv
sudo -u www-data /var/www/clinicnet/triage_venv/bin/pip install -r requirements.txt
sudo -u www-data cp .env.example .env
sudo -u www-data $EDITOR .env   # TELEGRAM_BOT_TOKEN, DJANGO_SERVICE_PASSWORD (пароль из шага выше), и т.д.
sudo chmod 600 .env

cp /var/www/clinicnet/deploy/systemd/clinicnet-triage.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now clinicnet-triage
systemctl status clinicnet-triage   # active (running)
curl -s http://127.0.0.1:8100/health   # {"status":"ok","polling":true}
```

## Обновления

```bash
cd /var/www/clinicnet
sudo -u www-data git pull
sudo -u www-data venv/bin/pip install -r requirements.txt
sudo -u www-data venv/bin/python manage.py collectstatic --noinput
sudo -u www-data venv/bin/python manage.py migrate_schemas --shared --noinput
sudo -u www-data venv/bin/python manage.py migrate_schemas --schema=clinicnet
sudo -u www-data venv/bin/python manage.py tenant_command seed_rbac --schema=clinicnet
systemctl restart clinicnet

# Если менялся triage_service/ (не при каждом обновлении):
sudo -u www-data /var/www/clinicnet/triage_venv/bin/pip install -r triage_service/requirements.txt
systemctl restart clinicnet-triage
```

`seed_rbac` идемпотентна — безопасно гонять её при каждом обновлении, а
не только когда точно знаешь, что добавились новые коды прав. Например,
Phase 3 шаг (d) (склад, `apps.inventory`) добавил `inventory.manage` /
`inventory.view` / `inventory.stock.manage` и выдал их существующим
ролям (`branch-admin`, `doctor`) — без повторного запуска `seed_rbac`
после `git pull` эти права не появятся у уже созданных ролей сети, и
склад будет недоступен всем, у кого нет `network-admin`.

## Диагностика

```bash
journalctl -u clinicnet -f
tail -f /var/log/nginx/clinicnet-stom-asia-error.log
```

Продление сертификата — уже автоматическое (`certbot.timer` активен на
сервере и обслуживает все домены разом, отдельно для ClinicNet ничего не
нужно).
