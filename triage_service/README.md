# AI-триаж — ClinicNet Phase 5, под-модуль 2

Отдельный сервис (FastAPI), не часть Django-проекта — намеренно, чтобы
LLM-инференс не грузил транзакционную БД (см. `docs/PHASE5-TRIAGE-DESIGN.md`
для полного обоснования архитектуры). Читает данные ClinicNet только через
уже существующий REST API (никакого прямого доступа к Postgres и никакой
read-replica — см. тот же design-документ).

Пациент пишет жалобу в Telegram → эвристика/LLM подбирает специальность →
сервис ищет ближайший слот, переиспользуя `available_slots` (Фаза 2,
`apps.referrals`) → создаёт `TriageSuggestion` через ingest-API → координатор
в ClinicNet подтверждает или отклоняет предложение; подтверждение создаёт
реальный `Appointment`. **Сам бот ничего не бронирует напрямую.**

## Установка

```bash
cd triage_service
python3 -m venv .venv   # отдельное окружение, не .venv Django-проекта
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # см. переменные ниже
```

## Переменные окружения (`.env`)

| Переменная | Обязательна | Описание |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | да | Токен бота от @BotFather. |
| `ANTHROPIC_API_KEY` | нет | Если пусто — используется встроенный keyword-классификатор (`classifier.KeywordSpecialtyClassifier`), сервис полностью рабочий без него. Если задан — автоматически переключается на реальный LLM (`classifier.AnthropicSpecialtyClassifier`), без изменений кода. |
| `DJANGO_API_BASE_URL` | да | Полный origin REST API **с хостом конкретной сети клиник** — django-tenants маршрутизирует по Host-заголовку, не по пути. Прод: `https://clinicnet.stom.asia`. |
| `DJANGO_SERVICE_USERNAME` / `DJANGO_SERVICE_PASSWORD` | да | Учётные данные выделенного сервисного аккаунта (роль `triage-bot`, только `triage.ingest`, `branch_scope=ALL`) — см. `docs/DEPLOY.md`, раздел «Сервисный аккаунт AI-триажа». |
| `SLOT_SEARCH_HORIZON_DAYS` | нет (по умолчанию 14) | Сколько дней вперёд искать ближайший слот, прежде чем сдаться. |

**`.env` никогда не коммитится** — корневой `.gitignore` репозитория уже
исключает `.env` на любом уровне вложенности.

## Запуск (dev)

```bash
uvicorn triage_service.main:app --reload --port 8100
```

`GET /health` — простой liveness-чек (используется systemd/мониторингом,
см. `deploy/systemd/clinicnet-triage.service`).

## Известные ограничения первого среза

- Состояние диалога (какой этап опроса пациента) хранится в памяти процесса
  (`bot.py`'s `_sessions`) — рестарт сервиса теряет незавершённые диалоги.
  Завершённые (уже дошедшие до ingest) — не теряются, они уже в БД ClinicNet.
- Только Telegram (long polling, не webhook) — WhatsApp и переход на webhook
  оставлены явным следующим шагом (см. `docs/PHASE5-TRIAGE-DESIGN.md`).
- Один сервис = одна сеть клиник (`DJANGO_API_BASE_URL` фиксирован на один
  tenant-хост) — если понадобится один бот на несколько сетей сразу,
  потребуется отдельная маршрутизация по `/start`-диплинку.
