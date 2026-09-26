# Ознакомление с РД

Система уведомления подрядчиков об ознакомлении с рабочей документацией (Sarex).

- Требования — [`TZ_uvedomlenie_podryadchikov.md`](TZ_uvedomlenie_podryadchikov.md)
- Технические решения и правила разработки — [`CLAUDE.md`](CLAUDE.md)
- План по этапам — [`docs/PLAN.md`](docs/PLAN.md)
- Макеты экранов — [`mockups/index.html`](mockups/index.html)

## Запуск для разработки

Через Docker (приложение, воркер, Postgres, Mailpit):

```bash
cp .env.example .env            # задать POSTGRES_PASSWORD и SECRET_KEY
docker compose up --build
```

- приложение: http://localhost:8000, проверка: http://localhost:8000/health
- демо-данные как в макетах: `docker compose exec app python -m app.scripts.seed_demo`
- документация API: http://localhost:8000/api/docs
- письма (Mailpit): http://localhost:8025

Без Docker, на своём Postgres 16:

```bash
uv sync
uv run alembic upgrade head
uv run python -m app.scripts.seed_demo   # демо-данные, необязательно
uv run uvicorn app.main:app --reload
uv run python -m app.worker
```

## Проверки перед коммитом

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest                   # нужна БД: TEST_DATABASE_URL, по умолчанию rd:rd@localhost:5432/rd_test
```

## Сервер

```bash
docker compose -f docker-compose.yml up -d --build   # без dev-override: с Caddy и HTTPS
```

Подробная инструкция по развёртыванию появится на этапе 8.
