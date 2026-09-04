# Деплой ClinicNet — `clinicnet.stom.asia` (АРХИВ — старый сервер)

> **Устарело.** Проект переехал на новый, выделенный только под
> ClinicNet сервер, деплой там — через Docker, см. `docs/DEPLOY-DOCKER.md`.
> Этот файл оставлен как есть — история и справка по общему хосту
> `46.149.68.65`, если он ещё где-то используется.

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

Репозиторий приватный — обычный `git clone`/`git pull` по HTTPS без
креда падает 401 (GitHub с 2021 года не принимает пароль аккаунта для
git, только токен/ключ). Вместо токена в URL — **Deploy Key** (SSH,
read-only, привязанный к этому конкретному репозиторию, не к аккаунту
целиком): ключ живёт только на сервере, приватная часть никуда не
уходит.

`www-data`'s `$HOME` — это `/var/www` (дефолт Debian), который сам
`www-data` не может писать (см. ниже про npm-кэш — та же причина), так
что ключ и known_hosts кладём не в дефолтное `~/.ssh`, а внутрь
`/var/www/clinicnet` (её ниже создаём и чауним первой), и указываем
git путь к нему явно (`core.sshCommand`), а не полагаемся на дефолтный
`~/.ssh/config`.

```bash
mkdir -p /var/www/clinicnet
chown www-data:www-data /var/www/clinicnet

sudo -u www-data mkdir -p /var/www/clinicnet/.ssh
sudo -u www-data ssh-keygen -t ed25519 -f /var/www/clinicnet/.ssh/github_deploy_key -N "" -C "clinicnet-prod-deploy"
sudo -u www-data ssh-keyscan -t ed25519 github.com >> /var/www/clinicnet/.ssh/known_hosts
chmod 600 /var/www/clinicnet/.ssh/github_deploy_key
cat /var/www/clinicnet/.ssh/github_deploy_key.pub
```

Вставить вывод последней команды: репозиторий `Akmalidin/ClinicNet` →
Settings → Deploy keys → Add deploy key (например, title
`clinicnet-prod-server`). **"Allow write access" оставить
выключенным** — серверу нужно только `git pull`, не push.

```bash
cd /var/www/clinicnet
GIT_SSH_COMMAND="ssh -i /var/www/clinicnet/.ssh/github_deploy_key -o UserKnownHostsFile=/var/www/clinicnet/.ssh/known_hosts -o IdentitiesOnly=yes"
sudo -u www-data env GIT_SSH_COMMAND="$GIT_SSH_COMMAND" git clone git@github.com:Akmalidin/ClinicNet.git .
sudo -u www-data git config core.sshCommand "$GIT_SSH_COMMAND"   # чтобы дальнейшие pull/fetch не требовали переменную заново
sudo -u www-data git checkout claude/odontis-enterprise-phased-plan-tal1n4   # до мержа PR #19 в main
sudo -u www-data python3 -m venv venv
sudo -u www-data venv/bin/pip install -r requirements.txt
```

Фронтенд (Vue) собирается отдельно от Django — сам бэкенд его не отдаёт
вообще (никакого catch-all/`TemplateView` в `config/urls.py`), это
целиком забота nginx (см. `deploy/nginx/clinicnet-stom-asia`: `/api/` и
`/admin/` идут в gunicorn, всё остальное — собранный SPA с фолбэком на
`index.html`). Сборка кладётся в `/var/www/clinicnet/frontend-dist/` —
путь, который тот vhost и ожидает. Требует Node.js — на сервере до этого
ставился только Python-стек (SADAF/ERP/CRM — все на gunicorn), так что
`npm` может не быть вообще; проверить `node -v` и при отсутствии
поставить один раз на весь сервер (Node 20 LTS, systemwide — как и
Python-стек, не per-app):

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
node -v && npm -v   # v20.x / 10.x
```

`www-data`'s home directory resolves to `/var/www` (Debian default), so
`sudo -u www-data npm ci` puts its cache at `/var/www/.npm` — but only
`/var/www/clinicnet` was chowned to `www-data` above, not `/var/www`
itself, so `www-data` can't create that directory on its own. Create it
once, as root, before the first build ever run on this server:

```bash
sudo mkdir -p /var/www/.npm
sudo chown -R 33:33 /var/www/.npm   # 33 = www-data's uid/gid on Debian/Ubuntu
```

```bash
cd /var/www/clinicnet/frontend
sudo -u www-data npm ci
sudo -u www-data npm run build
sudo -u www-data rm -rf /var/www/clinicnet/frontend-dist
sudo -u www-data cp -r dist /var/www/clinicnet/frontend-dist
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

nginx (обычно `www-data` в его собственном воркер-процессе) должен иметь
право на чтение `/var/www/clinicnet/frontend-dist/` — если каталог
создавался под `www-data:www-data` (как и остальной `/var/www/clinicnet`
в шаге 3), отдельно ничего настраивать не нужно.

Проверить: `curl -I https://clinicnet.stom.asia/admin/` — ожидается `200`
или `302` с валидным сертификатом; `curl -I https://clinicnet.stom.asia/`
— `200` (отдаёт `index.html` собранного фронтенда).

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

# Фронтенд — пересобирается на КАЖДОМ обновлении, не только когда точно
# знаешь, что менялся frontend/: gunicorn его не отдаёт вообще, старая
# сборка в frontend-dist/ иначе тихо продолжит обслуживаться nginx.
cd /var/www/clinicnet/frontend
sudo -u www-data npm ci
sudo -u www-data npm run build
sudo -u www-data rm -rf /var/www/clinicnet/frontend-dist
sudo -u www-data cp -r dist /var/www/clinicnet/frontend-dist

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
