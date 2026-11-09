from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import URL, create_engine, delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .models import Activity, ActivityKind, Base, Pet, PetDetails, PetNotFoundError, StorageError


class PetRegistry:
    """Хранилище карточек и журнала с общей транзакцией для каждой записи."""

    def __init__(self, database_url: str | URL) -> None:
        self._engine = create_engine(database_url, pool_pre_ping=True)
        self._sessions = sessionmaker(self._engine, expire_on_commit=False)
        try:
            Base.metadata.create_all(self._engine)
        except SQLAlchemyError as error:
            self.close()
            raise StorageError("Не удалось открыть базу данных.") from error

    def close(self) -> None:
        self._engine.dispose()

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        try:
            with self._sessions.begin() as session:
                yield session
        except SQLAlchemyError as error:
            raise StorageError("Не удалось выполнить операцию с базой данных.") from error

    def list_pets(self) -> list[Pet]:
        with self._transaction() as session:
            return list(session.scalars(select(Pet).order_by(Pet.id)))

    def get_pet(self, pet_id: int) -> Pet:
        with self._transaction() as session:
            pet = session.get(Pet, pet_id)
            if pet is None:
                raise PetNotFoundError("Карточка питомца не найдена.")
            return pet

    def add_pet(self, details: PetDetails) -> Pet:
        with self._transaction() as session:
            pet = Pet(**asdict(details))
            session.add(pet)
            session.flush()
            self._log(session, ActivityKind.ADDED, pet.id, pet.name)
            return pet

    def update_pet(self, pet_id: int, details: PetDetails) -> Pet:
        statement = update(Pet).where(Pet.id == pet_id).values(**asdict(details)).returning(Pet)
        with self._transaction() as session:
            pet = session.scalar(statement)
            if pet is None:
                raise PetNotFoundError("Карточка питомца не найдена.")
            self._log(session, ActivityKind.UPDATED, pet.id, pet.name)
            return pet

    def delete_pet(self, pet_id: int) -> None:
        statement = delete(Pet).where(Pet.id == pet_id).returning(Pet.name)
        with self._transaction() as session:
            name = session.scalar(statement)
            if name is None:
                raise PetNotFoundError("Карточка питомца не найдена.")
            self._log(session, ActivityKind.DELETED, pet_id, name)

    def recent_activity(self) -> list[Activity]:
        statement = select(Activity).order_by(Activity.occurred_at.desc(), Activity.id.desc()).limit(50)
        with self._transaction() as session:
            return list(session.scalars(statement))

    def daily_activity(self) -> list[tuple[date, int]]:
        today = datetime.now(UTC).date()
        first_day = today - timedelta(days=6)
        start = datetime.combine(first_day, time.min)
        stop = datetime.combine(today + timedelta(days=1), time.min)
        statement = select(Activity.occurred_at).where(
            Activity.occurred_at >= start, Activity.occurred_at < stop
        )
        with self._transaction() as session:
            counts = Counter(moment.date() for moment in session.scalars(statement))
        days = [first_day + timedelta(days=offset) for offset in range(7)]
        return [(day, counts[day]) for day in days]

    @staticmethod
    def _log(session: Session, kind: ActivityKind, pet_id: int, pet_name: str) -> None:
        session.add(Activity(
            kind=kind,
            pet_id=pet_id,
            pet_name=pet_name,
            # SQLite и PostgreSQL хранят одинаковое время UTC без смещения.
            occurred_at=datetime.now(UTC).replace(tzinfo=None),
        ))
