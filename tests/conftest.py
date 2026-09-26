import os

# Tests never read the developer's .env: the database comes from TEST_DATABASE_URL.
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://rd:rd@localhost:5432/rd_test"),
)
os.environ["APP_ENV"] = "test"
