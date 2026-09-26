# CLAUDE.md

Система уведомления подрядчиков об ознакомлении с рабочей документацией (Sarex).
Полное техническое задание — `TZ_uvedomlenie_podryadchikov.md`. При расхождении этого файла и ТЗ источником требований считается ТЗ, а этот файл — источником технических решений.

## Статус проекта

Кода пока нет, есть только ТЗ. Стек ниже выбран и зафиксирован; раздел 10 ТЗ («Рекомендуемый стек, для обсуждения») этим закрыт.

## Стек

| Слой | Выбор | Почему |
|---|---|---|
| Язык | Python 3.12 | единый язык для бэкенда, воркера и шаблонов |
| Веб-фреймворк | FastAPI + Uvicorn | async, OpenAPI из коробки, Pydantic-валидация |
| ORM | SQLAlchemy 2.0 (async, стиль `Mapped[...]`) + драйвер `asyncpg` | требование команды |
| Миграции | Alembic | стандарт для SQLAlchemy |
| БД | PostgreSQL 16 | `jsonb` для `notification_events.payload` (раздел 3.5 ТЗ) |
| Схемы и настройки | Pydantic v2, `pydantic-settings` (конфиг из переменных окружения) | |
| Фоновые задачи | отдельный контейнер `worker` с APScheduler (`AsyncIOScheduler`) | без Redis/Celery: на VPS с 1–2 ГБ RAM (раздел 12.1) лишний брокер не нужен, а нагрузка — десятки уведомлений в день |
| Интерфейс координатора | серверный рендеринг: Jinja2 + HTMX (+ минимальный CSS, без сборщика) | CRM-доска и формы (раздел 7) не требуют SPA; нет Node.js-тулчейна и отдельного фронтенд-контейнера. React из раздела 10 ТЗ сознательно не используется |
| Отправка почты | SMTP транзакционного провайдера через `aiosmtplib` | провайдер меняется одной настройкой |
| Приём ответов | адаптер `InboundMailSource`: webhook провайдера (`POST /api/webhooks/email-inbound`) или IMAP-поллинг в воркере | выбор зависит от открытого вопроса 1 ТЗ; бизнес-логика не должна знать, откуда пришло письмо |
| ИИ-классификация | официальный SDK `anthropic` (`AsyncAnthropic`), `client.messages.parse(...)` с Pydantic-моделью ответа | структурированный JSON `category / confidence / reasoning` (раздел 4.2 ТЗ) |
| Аутентификация | логин/пароль, хеш `argon2` (`pwdlib`), серверная сессия в cookie | SSO — открытый вопрос раздела 8; закладываем замену через отдельный модуль `auth` |
| Инструменты | `uv` (зависимости и lock-файл), `ruff` (lint + format), `mypy`, `pytest` + `pytest-asyncio` | |
| Развёртывание | Docker + docker compose, Caddy (reverse proxy + автоматический Let's Encrypt) | раздел 12 ТЗ; Caddy выпускает и продлевает сертификат сам, без certbot |

### ИИ-классификатор: договорённости

- Модель задаётся переменной `LLM_MODEL`, по умолчанию `claude-opus-5`. Менять модель — только через env, не в коде.
- Вызов: `client.messages.parse(model=..., max_tokens=..., system=..., messages=[...], output_format=ClassificationResult)`, где `ClassificationResult` — Pydantic-модель с полями `category`, `confidence`, `reasoning`. Результат — `response.parsed_output`. Перед чтением результата проверять `response.stop_reason` (в т.ч. `refusal`).
- Если `confidence < AI_CONFIDENCE_THRESHOLD` (env, по умолчанию `0.7`) — категория принудительно `unclear` (раздел 4.2 ТЗ).
- Ошибки API ловить цепочкой от частных к общим (`RateLimitError` → `APIStatusError` → `APIConnectionError`), при недоступности модели — fallback на keyword-match (`services/classifier/keywords.py`), результат помечать в `payload` как `"classifier": "keywords"`.
- Сохранять в `notification_events` исходный текст, категорию, уверенность и `reasoning` — всегда, а не только «на лету».
- Системный промпт хранится в `app/services/classifier/prompt.py` как константа, без динамических вставок (дата, id), чтобы он кешировался.
- Если по результатам открытого вопроса 6 (ИБ) переписку нельзя отправлять во внешний API — меняется только реализация `Classifier`, интерфейс остаётся.

## Структура проекта

```
.
├── app/
│   ├── main.py                 # создание FastAPI-приложения, подключение роутеров
│   ├── config.py               # Settings (pydantic-settings), все параметры из env
│   ├── db.py                   # async engine, sessionmaker, зависимость get_session
│   ├── models/                 # SQLAlchemy-модели по разделу 3 ТЗ: object, corpus, contractor, user,
│   │                           #   notification, notification_event, holiday
│   ├── schemas/                # Pydantic-схемы запросов/ответов API
│   ├── api/                    # JSON API (раздел 5 ТЗ): objects, notifications,
│   │                           #   dashboard, webhooks, ack
│   ├── web/                    # HTML-интерфейс координатора
│   │   ├── routes.py
│   │   ├── templates/          # Jinja2: board, notification_card, send_form, login
│   │   └── static/             # CSS, htmx.min.js
│   ├── services/               # вся бизнес-логика
│   │   ├── notifications.py    # создание, смена статусов, запись событий
│   │   ├── reminders.py        # логика напоминаний и эскалации (раздел 4.3)
│   │   ├── workdays.py         # расчёт рабочих дней с учётом таблицы holidays
│   │   ├── classifier/         # ИИ-классификатор + keyword fallback + промпт
│   │   ├── mail/               # sender.py (SMTP), inbound.py (webhook/IMAP), templates/
│   │   └── telegram/           # задел под раздел 11, в MVP пусто
│   ├── auth/                   # логин, сессии, зависимость current_user
│   └── worker.py               # точка входа контейнера worker: APScheduler-задачи
├── migrations/                 # Alembic
├── tests/
│   ├── unit/                   # workdays, reminders, классификатор (с моками)
│   └── integration/            # API и сервисы на реальном Postgres
├── deploy/
│   ├── Caddyfile
│   └── backup.sh               # pg_dump + ротация, запускается cron'ом на хосте
├── Dockerfile                  # один образ для app и worker (разные command)
├── docker-compose.yml          # prod: app, worker, db, caddy
├── docker-compose.override.yml # dev: проброс портов, reload, без caddy
├── pyproject.toml / uv.lock
├── .env.example                # все переменные с пояснениями, без реальных значений
├── TZ_uvedomlenie_podryadchikov.md
└── CLAUDE.md
```

Слои: `api/` и `web/` только принимают запрос, валидируют и вызывают `services/`. SQL-запросы и смена статусов — только в `services/`. `models/` не импортирует ничего из `services/`.

## Развёртывание (раздел 12 ТЗ)

Целевой сервер: VPS 1 vCPU / 1–2 ГБ RAM / 20–25 ГБ SSD, Ubuntu LTS, домен с HTTPS.

Контейнеры `docker-compose.yml`:

| Сервис | Образ | Назначение |
|---|---|---|
| `db` | `postgres:16-alpine` | данные в именованном volume; порт наружу не публикуется |
| `app` | собственный | `alembic upgrade head` при старте, затем `uvicorn app.main:app` (1–2 воркера) |
| `worker` | тот же образ | `python -m app.worker`; ровно один экземпляр |
| `caddy` | `caddy:2-alpine` | 80/443, TLS, проксирование на `app:8000` |

Правила:
- Наружу открыты только 80/443 (и 22 для SSH на уровне хоста). Postgres и app — только во внутренней сети compose.
- Каждому сервису задан `mem_limit` и `restart: unless-stopped`; суммарно должно помещаться в 1 ГБ RAM с запасом.
- Секреты (`DATABASE_URL`, `ANTHROPIC_API_KEY`, SMTP-учётка, `SECRET_KEY`, `WEBHOOK_SECRET`) — только в `.env` на сервере, в git попадает лишь `.env.example`.
- Бэкап: ежедневный `deploy/backup.sh` (cron хоста) → `pg_dump -Fc` → копия во внешнее хранилище, хранить минимум 14 дней. Потеря БД = потеря всей истории ознакомлений, поэтому восстановление из бэкапа проверяется до запуска в работу.
- Логи — в stdout контейнеров (docker сам ротирует при `json-file` с `max-size`).
- CI/CD (раздел 12.4) — позже: GitHub Actions, при мерже в `main` — сборка образа и `docker compose pull && docker compose up -d` по SSH.

Локальный запуск:
```bash
cp .env.example .env
docker compose up --build        # с override: app на localhost:8000, БД на localhost:5432
docker compose exec app alembic upgrade head
```

## Правила разработки

### Код
- Идентификаторы, комментарии в коде и сообщения коммитов — на английском. Тексты интерфейса, писем и документация для пользователей — на русском.
- Типизация обязательна (`mypy --strict` для `app/`). SQLAlchemy-модели — только в стиле 2.0 (`Mapped`, `mapped_column`), без legacy `Query`.
- Работа с БД — только async (`AsyncSession`). Одна сессия на запрос/задачу, транзакции — через `async with session.begin()`.
- Все даты — `timestamptz`, в коде — timezone-aware `datetime` в UTC. Перевод в локальное время (`APP_TIMEZONE`, по умолчанию `Europe/Moscow`) — только при отображении и при расчёте рабочих дней.
- Enum-ы из ТЗ (`status`, `channel`, `ai_category`, `event type`) — Python `enum.StrEnum`, в БД как `sa.Enum(..., native_enum=False)` (строка + CHECK), чтобы добавление значений не требовало `ALTER TYPE`.
- Все настраиваемые пороги и интервалы (порог уверенности ИИ, 1/3/10 рабочих дней, время запуска cron) — в `Settings`, не хардкодом.

### Бизнес-инварианты
- Любое исходящее или входящее сообщение (письмо, напоминание, эскалация, ответ подрядчика, Telegram) создаёт запись в `notification_events` с полным `raw_content`. Нет события — не было действия.
- Статус уведомления меняется только функциями `services/notifications.py`; прямое присваивание `notification.status = ...` вне этого модуля запрещено.
- Задача напоминаний идемпотентна: выборка с `SELECT ... FOR UPDATE SKIP LOCKED`, обновление с условием на текущий `reminder_count`/`status`, письмо отправляется после фиксации изменения. Повторный запуск в тот же день не должен отправить второе письмо.
- Ответ, классифицированный как `unclear`, не меняет статус автоматически.
- Магическая ссылка подтверждения — одноразовый подписанный токен (`itsdangerous` или HMAC c `SECRET_KEY`), с ограниченным сроком жизни.
- Webhook-эндпоинты проверяют подпись/секрет провайдера; без проверки запрос отклоняется.

### Модель данных
- Таблицы и поля — строго по разделу 3 ТЗ (включая `users`, `holidays`, `notifications.needs_manual_review`, `objects.project_manager_email`). Новое поле или таблица сначала добавляется в ТЗ, потом в код.

### Миграции
- Любое изменение моделей — новая миграция Alembic (`alembic revision --autogenerate -m "..."`), сгенерированный файл обязательно просматривается и правится руками.
- Уже применённые миграции не редактируются.

### Тесты и проверки
Перед каждым коммитом должно проходить:
```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest
```
- Бизнес-логика (`workdays`, `reminders`, переходы статусов, порог уверенности) покрывается unit-тестами обязательно.
- LLM и SMTP в тестах мокаются; реальные вызовы внешних API в тестах запрещены.
- Интеграционные тесты идут на настоящем Postgres (сервис `db` из compose или отдельная тестовая БД), не на SQLite.

### Git
- Ветки от `main`, изменения — через pull request.
- Один PR — одна логическая задача; миграция идёт в том же PR, что и изменение модели.
- Секреты, `.env`, дампы БД в репозиторий не коммитятся.
