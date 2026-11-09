from os import getenv
from pathlib import Path

from sqlalchemy import URL

from .models import StorageError


PROJECT_DIR = Path(__file__).resolve().parent.parent


def resolve_database_url() -> URL:
    host = getenv("PET_REGISTRY_DB_HOST")
    if not host:
        return URL.create("sqlite", database=str(PROJECT_DIR / "pets.sqlite3"))

    password = getenv("POSTGRES_PASSWORD")
    if password is None:
        try:
            from dotenv import dotenv_values
        except ModuleNotFoundError as error:
            raise StorageError("Для чтения .env установите зависимости из requirements.txt.") from error
        password = dotenv_values(PROJECT_DIR / ".env", interpolate=False).get("POSTGRES_PASSWORD")
    if not password:
        raise StorageError("Укажите пароль PostgreSQL в переменной POSTGRES_PASSWORD или файле .env.")

    try:
        port = int(getenv("PET_REGISTRY_DB_PORT", "55432"))
    except ValueError as error:
        raise StorageError("Порт PostgreSQL должен быть числом от 1 до 65535.") from error
    if not 1 <= port <= 65535:
        raise StorageError("Порт PostgreSQL должен быть числом от 1 до 65535.")

    return URL.create(
        "postgresql+psycopg",
        username="pets",
        password=password,
        host=host,
        port=port,
        database="pets",
        query={"connect_timeout": "5"},
    )
