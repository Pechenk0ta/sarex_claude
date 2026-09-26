# CLAUDE.md

Система уведомления подрядчиков об ознакомлении с рабочей документацией (Sarex).
Полное техническое задание — `TZ_uvedomlenie_podryadchikov.md`. При расхождении этого файла и ТЗ источником требований считается ТЗ, а этот файл — источником технических решений.

## Статус проекта

Кода пока нет: есть ТЗ, утверждённые макеты (`mockups/index.html`) и план разработки по этапам (`docs/PLAN.md`). Стек ниже выбран и зафиксирован; раздел 10 ТЗ («Рекомендуемый стек, для обсуждения») этим закрыт.

Макеты утверждены: вёрстка шаблонов повторяет их. Меняться может только цветовая гамма, поэтому все цвета — CSS-переменные в одном блоке `:root` файла `app/web/static/app.css` (плюс тёмная тема), без цветов, заданных напрямую в правилах.

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
| Отправка почты | SMTP ящика системы в Microsoft 365 (`smtp.office365.com:587`, STARTTLS) через `aiosmtplib` с аутентификацией XOAUTH2; токен — `msal` (client credentials) | решение 1 раздела 9 ТЗ: вся переписка видна в Outlook; способ входа спрятан в `services/mail/auth.py`, чтобы при переезде ящика (например, на Яндекс 360 с паролем приложения) менялся только он |
| Приём ответов | IMAP-поллинг того же ящика в воркере (`outlook.office365.com:993`, `aioimaplib`, XOAUTH2 тем же токеном), уведомление находится по plus-адресу `rd+<токен>@домен` из заголовков `To`/`Delivered-To`; за интерфейсом `InboundMailSource` | обработанные письма помечаются флагом/папкой в ящике, а не удаляются; повторная обработка одного письма (по `Message-ID`) ничего не меняет |
| ИИ-классификация | YandexGPT Lite (Yandex Cloud) за интерфейсом `Classifier`, запасной вариант — `KeywordClassifier` | раздел 9 ТЗ, решение 7: данные в РФ, около 0,4 ₽ за ответ; структурированный JSON `category / confidence / reasoning` (раздел 4.2 ТЗ) |
| Аутентификация | логин/пароль, хеш `argon2` (`pwdlib`), серверная сессия в cookie | SSO — открытый вопрос раздела 8; закладываем замену через отдельный модуль `auth` |
| Инструменты | `uv` (зависимости и lock-файл), `ruff` (lint + format), `mypy`, `pytest` + `pytest-asyncio` | |
| Развёртывание | Docker + docker compose, Caddy (reverse proxy + автоматический Let's Encrypt) | раздел 12 ТЗ; Caddy выпускает и продлевает сертификат сам, без certbot |

### ИИ-классификатор: договорённости

- Провайдер — **YandexGPT Lite** в Yandex Cloud (раздел 9 ТЗ, решение 7): данные остаются в РФ, платный аккаунт компании. Реализация выбирается переменной `CLASSIFIER`: `yandexgpt` в работе, `keywords` — для локальной разработки и тестов. Ни бизнес-логика, ни БД от реализации не зависят.
- Доступ: сервисный аккаунт Yandex Cloud с ролью на использование моделей, API-ключ в `YANDEX_API_KEY`, каталог в `YANDEX_FOLDER_ID`, модель в `YANDEX_GPT_MODEL` (по умолчанию `yandexgpt-lite`). Менять модель — только через env, не в коде. Клиент — официальный SDK Yandex Cloud ML для Python либо HTTP API; точные вызовы брать из документации Yandex Cloud, не по памяти.
- Ответ модели запрашивается в виде JSON по схеме `ClassificationResult` (Pydantic: `category`, `confidence`, `reasoning`) и обязательно валидируется Pydantic. Невалидный JSON, неизвестная категория, таймаут или ошибка API — не авария: ответ классифицируется по ключевым словам (`services/classifier/keywords.py`), в `payload` пишется `"classifier": "keywords"` и причина, координатор видит это в карточке.
- Если `confidence < AI_CONFIDENCE_THRESHOLD` (env, по умолчанию `0.7`) — категория принудительно `unclear` (раздел 4.2 ТЗ). Уверенность, которую модель сообщает сама, может быть плохо откалибрована — порог подбирается на реальных ответах во время пилота.
- В запросах к модели отключать логирование данных на стороне Yandex Cloud, если API это позволяет (проверить по документации при реализации).
- Сохранять в `notification_events` исходный текст, категорию, уверенность, `reasoning` и название модели — всегда, а не только «на лету».
- Системный промпт хранится в `app/services/classifier/prompt.py` как константа; текст письма передаётся отдельным сообщением пользователя, а не вклеивается в инструкцию.
- Качество проверяется набором из 20–30 обезличенных реальных ответов подрядчиков (`tests/fixtures/replies/`) с ожидаемой категорией; в CI модель подменяется, живой прогон — вручную перед сменой промпта или модели.

## Структура проекта

```
.
├── app/
│   ├── main.py                 # создание FastAPI-приложения, подключение роутеров
│   ├── config.py               # Settings (pydantic-settings), все параметры из env
│   ├── db.py                   # async engine, sessionmaker, зависимость get_session
│   ├── models/                 # SQLAlchemy-модели по разделу 3 ТЗ: project, corpus, contractor, project_contractor, user,
│   │                           #   notification, notification_event, holiday
│   ├── schemas/                # Pydantic-схемы запросов/ответов API
│   ├── api/                    # JSON API (раздел 5 ТЗ): projects, notifications,
│   │                           #   dashboard, ack
│   ├── web/                    # HTML-интерфейс координатора
│   │   ├── routes.py
│   │   ├── templates/          # Jinja2: board, notification_card, send_form, login
│   │   └── static/             # CSS, htmx.min.js
│   ├── services/               # вся бизнес-логика
│   │   ├── notifications.py    # создание, смена статусов, запись событий
│   │   ├── reminders.py        # логика напоминаний и эскалации (раздел 4.3)
│   │   ├── workdays.py         # расчёт рабочих дней с учётом таблицы holidays
│   │   ├── classifier/         # ИИ-классификатор + keyword fallback + промпт
│   │   ├── mail/               # auth.py (OAuth2 M365), sender.py (SMTP), inbound.py (IMAP), templates/
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
├── docker-compose.override.yml # dev: проброс портов, reload, Mailpit для писем, без caddy
├── docs/PLAN.md                # план разработки по этапам
├── mockups/index.html          # утверждённые статичные макеты экранов
├── pyproject.toml / uv.lock
├── .env.example                # все переменные с пояснениями, без реальных значений
├── TZ_uvedomlenie_podryadchikov.md
└── CLAUDE.md
```

Слои: `api/` и `web/` только принимают запрос, валидируют и вызывают `services/`. SQL-запросы и смена статусов — только в `services/`. `models/` не импортирует ничего из `services/`.

## Развёртывание (раздел 12 ТЗ)

Целевой сервер: российский VPS (данные хранятся в РФ, раздел 9 ТЗ, решение 3) 1 vCPU / 1–2 ГБ RAM / 20–25 ГБ SSD, Ubuntu LTS, домен с HTTPS.

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
- Секреты (`DATABASE_URL`, `MS_TENANT_ID` / `MS_CLIENT_ID` / `MS_CLIENT_SECRET` приложения Entra ID, адрес ящика, `YANDEX_API_KEY`, `YANDEX_FOLDER_ID`, `SECRET_KEY`) — только в `.env` на сервере, в git попадает лишь `.env.example`.
- Бэкап: ежедневный `deploy/backup.sh` (cron хоста) → `pg_dump -Fc` → копия во внешнее хранилище, хранить минимум 14 дней. Потеря БД = потеря всей истории ознакомлений, поэтому восстановление из бэкапа проверяется до запуска в работу.
- Логи — в stdout контейнеров (docker сам ротирует при `json-file` с `max-size`).
- CI/CD (раздел 12.4) — позже: GitHub Actions, при мерже в `main` — сборка образа и `docker compose pull && docker compose up -d` по SSH.

Локальный запуск:
```bash
cp .env.example .env
docker compose up --build        # с override: app на localhost:8000, БД на localhost:5432, письма — в Mailpit на localhost:8025
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
- Webhook-эндпоинты (Telegram, раздел 11 ТЗ) проверяют секрет; без проверки запрос отклоняется.
- Письма в IMAP-ящике не удаляются: это архив переписки, который смотрят люди.

### Модель данных
- Таблицы и поля — строго по разделу 3 ТЗ (включая `project_contractors`, `users`, `holidays`, `notifications.needs_manual_review`, `projects.project_manager_email`). Новое поле или таблица сначала добавляется в ТЗ, потом в код.

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
