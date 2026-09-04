# Деплой ClinicNet (Docker) — новый выделенный сервер

Замена `docs/DEPLOY.md` (архивирован, см. пометку в начале того файла).
Тот гайд был написан под общий сервер `46.149.68.65`, где ClinicNet жил
рядом с SADAF/ERP/CRM за одним nginx и общим Postgres — отсюда venv +
systemd-юнит + отдельный vhost, ничего не трогая у соседей.

Новый сервер **выделен только под ClinicNet** — эти ограничения не
действуют, поэтому весь стек теперь один `docker compose`: Django/gunicorn
+ Postgres + AI-триаж (FastAPI) + nginx + certbot, каждый в своём
контейнере. Домен тот же — `clinicnet.stom.asia`, просто DNS A-запись
переезжает на новый IP и сертификат Let's Encrypt выпускается заново (на
старом сервере был общий wildcard-сертификат `*.stom.asia`, здесь его нет).

## 0. Что нужно на сервере заранее

- Docker Engine + плагин `docker compose` (v2, команда `docker compose`,
  не отдельный `docker-compose`). Если не установлены:
  ```bash
  curl -fsSL https://get.docker.com | sh
  ```
  (официальный скрипт Docker; ставит и Engine, и compose-плагин).
- Открытые порты `80` и `443` (входящие) — больше ничего наружу торчать
  не должно: Postgres, gunicorn и триаж-сервис в этом стеке не публикуют
  портов на хост вообще, только внутри docker-сети (см. `docker-compose.yml`).

## 1. DNS

В панели DNS-провайдера для `stom.asia`: поменять A-запись
`clinicnet.stom.asia` на IP нового сервера. Дать записи разойтись
(обычно минуты, иногда до пары часов) — TLS-выпуск в шаге 4 не сработает,
пока домен резолвится в старый IP.

## 2. Код на сервере

```bash
git clone https://github.com/Akmalidin/ClinicNet.git /opt/clinicnet
cd /opt/clinicnet
git checkout claude/odontis-enterprise-phased-plan-tal1n4
```

Репозиторий приватный — HTTPS-клон без креда упадёт с 401 (GitHub не
принимает пароль аккаунта для git с 2021 года). Быстрее всего здесь —
**Personal Access Token** (в URL клона) или тот же **Deploy Key**-подход,
что описан в архивной `docs/DEPLOY.md` (раздел 3) — оба варианта рабочие,
выбор не принципиален для нового сервера (он не общий, чужого доступа
опасаться не от кого).

## 3. Секреты (`.env`)

```bash
cd /opt/clinicnet
cp .env.docker.example .env
$EDITOR .env   # SECRET_KEY, DB_PASSWORD — сгенерировать длинные случайные значения
chmod 600 .env

cp triage_service/.env.example triage_service/.env
$EDITOR triage_service/.env   # TELEGRAM_BOT_TOKEN, DJANGO_SERVICE_PASSWORD (см. шаг 6), ANTHROPIC_API_KEY (опционально)
chmod 600 triage_service/.env
```

`DB_HOST=db` в `.env.docker.example` — это имя сервиса Postgres в
docker-сети (см. `docker-compose.yml`), не адрес хоста; менять не нужно.

## 4. Сертификат и первый запуск

```bash
cd /opt/clinicnet
sh deploy/docker/certbot/init-letsencrypt.sh
```

Скрипт (см. комментарии внутри `deploy/docker/certbot/init-letsencrypt.sh`
за деталями) сам: поднимет временный self-signed сертификат, чтобы nginx
вообще смог стартовать → запустит `nginx` → получит настоящий сертификат
от Let's Encrypt через ACME HTTP-01 (порт 80) → перезагрузит nginx с ним.
После него `nginx` уже поднят; собрать и поднять остальное:

```bash
docker compose build
docker compose up -d
docker compose ps   # все сервисы — Up (db — healthy)
```

## 5. Миграции и первая сеть клиник

`web`-контейнер сам гоняет `collectstatic` и `migrate_schemas --shared`
при каждом старте (см. `deploy/docker/django-entrypoint.sh`). Схему
конкретного тенанта и его данные — вручную, один раз:

```bash
docker compose exec web python manage.py migrate_schemas --shared --noinput

docker compose exec web python manage.py create_tenant \
  --schema_name=clinicnet --name="ClinicNet" \
  --domain-domain=clinicnet.stom.asia --domain-is_primary=True --noinput

docker compose exec web python manage.py tenant_command seed_rbac --schema=clinicnet
```

Проверить: `curl -I https://clinicnet.stom.asia/admin/` → `200`/`302` с
валидным сертификатом; `curl -I https://clinicnet.stom.asia/` → `200`
(отдаёт собранный фронтенд).

## 6. Первый пользователь и сервисный аккаунт триаж-бота

```bash
docker compose exec web python manage.py tenant_command shell --schema=clinicnet
```

```python
from apps.accounts.models import User, Role, UserRole, BranchScope

u = User.objects.create_superuser(username="admin", password="<придумать пароль>")
role = Role.objects.get(codename="network-admin")
UserRole.objects.create(user=u, role=role, branch_scope=BranchScope.ALL)

bot = User.objects.create_user(username="triage_bot_service", password="<сгенерировать длинный пароль — тот же в triage_service/.env DJANGO_SERVICE_PASSWORD>")
role = Role.objects.get(codename="triage-bot")
UserRole.objects.create(user=bot, role=role, branch_scope=BranchScope.ALL)
exit()
```

Если пароль бота меняли уже после первого запуска `triage`-контейнера —
`docker compose restart triage`.

```bash
docker compose logs -f triage   # "Triage service started."
curl -s http://localhost:8100/health 2>/dev/null || docker compose exec triage curl -s http://localhost:8100/health
# {"status":"ok","polling":true}
```

## Обновления (после `git pull` новых коммитов)

```bash
cd /opt/clinicnet
git pull
docker compose build
docker compose up -d
docker compose exec web python manage.py migrate_schemas --schema=clinicnet
docker compose exec web python manage.py tenant_command seed_rbac --schema=clinicnet
```

`docker compose up -d` само пересоздаёт изменившиеся контейнеры (в т.ч.
`nginx` — фронтенд пересобирается заново на КАЖДОМ обновлении, он запечён
в образ на этапе сборки, см. `deploy/docker/nginx.Dockerfile`) и не
трогает те, что не изменились.

## Продление сертификата

Сертификат Let's Encrypt живёт 90 дней. Продление — точечный запуск
`certbot`-сервиса, не демон (см. комментарий в `docker-compose.yml`).
Добавить на хосте (не в контейнере) cron-запись или systemd-таймер:

```bash
# /etc/cron.d/clinicnet-certbot-renew
0 3 * * 1  root  cd /opt/clinicnet && docker compose run --rm certbot renew --quiet && docker compose exec nginx nginx -s reload
```

(еженедельно по понедельникам в 03:00 — certbot сам решает, продлевать
или нет, реально запрашивает новый сертификат только в последние ~30
дней до истечения текущего).

## Логи

```bash
docker compose logs -f web      # Django/gunicorn, включая clinicnet.security
docker compose logs -f triage   # AI-триаж
docker compose logs -f nginx
docker compose logs -f db
```

## Бэкап БД

```bash
docker compose exec db pg_dump -U clinicnet clinicnet | gzip > clinicnet-$(date +%F).sql.gz
```
