from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import Enum, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


TEXT_LIMIT = 100


class RegistryError(Exception):
    """Ошибка, которую интерфейс может показать пользователю."""


class PetValidationError(RegistryError):
    """Данные карточки питомца не прошли проверку."""


class PetNotFoundError(RegistryError):
    """Карточки с таким идентификатором нет."""


class StorageError(RegistryError):
    """Хранилище недоступно или операция не выполнена."""


@dataclass(frozen=True)
class PetDetails:
    name: str
    species: str
    owner: str
    breed: str = ""
    birth_date: date | None = None

    def __post_init__(self) -> None:
        text_fields = (
            ("name", "Кличка", True),
            ("species", "Вид", True),
            ("owner", "Владелец", True),
            ("breed", "Порода", False),
        )
        for field, label, required in text_fields:
            value = getattr(self, field).strip()
            if required and not value:
                raise PetValidationError(f'Заполните поле «{label}».')
            if len(value) > TEXT_LIMIT:
                raise PetValidationError(f'В поле «{label}» допустимо до {TEXT_LIMIT} символов.')
            if "\x00" in value:
                raise PetValidationError(f'В поле «{label}» есть недопустимый символ.')
            object.__setattr__(self, field, value)

        if self.birth_date is not None:
            if type(self.birth_date) is not date:
                raise PetValidationError("Укажите корректную дату рождения.")
            if self.birth_date > datetime.now(UTC).date():
                raise PetValidationError("Дата рождения не может быть в будущем.")


class Base(DeclarativeBase):
    pass


class Pet(Base):
    __tablename__ = "pets"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(TEXT_LIMIT))
    species: Mapped[str] = mapped_column(String(TEXT_LIMIT))
    owner: Mapped[str] = mapped_column(String(TEXT_LIMIT))
    breed: Mapped[str] = mapped_column(String(TEXT_LIMIT))
    birth_date: Mapped[date | None]


class ActivityKind(StrEnum):
    ADDED = "Добавление"
    UPDATED = "Редактирование"
    DELETED = "Удаление"


class Activity(Base):
    __tablename__ = "activity"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[ActivityKind] = mapped_column(Enum(ActivityKind, native_enum=False))
    # Снимок карточки сохраняется в журнале после её удаления.
    pet_id: Mapped[int]
    pet_name: Mapped[str] = mapped_column(String(TEXT_LIMIT))
    occurred_at: Mapped[datetime] = mapped_column(index=True)
