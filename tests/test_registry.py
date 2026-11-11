from contextlib import closing
from dataclasses import replace
from datetime import date, timedelta

import pytest
from PySide6.QtCharts import QBarSeries
from PySide6.QtWidgets import QApplication
from sqlalchemy import URL

from desktop import ActivityChart, PetForm
from pet_registry.models import (
    ActivityKind,
    Pet,
    PetDetails,
    PetNotFoundError,
    PetValidationError,
    parse_birth_date,
)
from pet_registry.storage import PetRegistry
from web_app.main import PetInput


@pytest.fixture
def registry(tmp_path):
    url = URL.create("sqlite", database=str(tmp_path / "pets.sqlite3"))
    with closing(PetRegistry(url)) as registry:
        yield registry


@pytest.fixture
def pet_details():
    return PetDetails("Луна", "Кошка", "Анна", birth_date=date(2024, 5, 12))


@pytest.fixture(scope="session")
def qt_app():
    with pytest.MonkeyPatch.context() as env:
        env.setenv("QT_QPA_PLATFORM", "offscreen")
        yield QApplication.instance() or QApplication([])


# Проверяет разбор даты рождения и ошибку для несуществующей даты.
def test_parse_birth_date():
    assert parse_birth_date("2024-05-12") == date(2024, 5, 12)
    with pytest.raises(PetValidationError):
        parse_birth_date("2024-02-30")


# Проверяет, что у карточки должна быть кличка.
def test_pet_details_requires_name():
    with pytest.raises(PetValidationError, match="Кличка"):
        PetDetails(" ", "Кошка", "Анна")


# Проверяет, что add_pet сохраняет карточку и записывает добавление в журнал.
def test_add_pet(registry, pet_details):
    pet = registry.add_pet(pet_details)

    assert registry.get_pet(pet.id).name == pet_details.name
    [event] = registry.recent_activity()
    assert (event.pet_id, event.kind) == (pet.id, ActivityKind.ADDED)


# Проверяет, что update_pet меняет владельца существующей карточки.
def test_update_pet(registry, pet_details):
    pet = registry.add_pet(pet_details)

    registry.update_pet(pet.id, replace(pet_details, owner="Ирина"))

    assert registry.get_pet(pet.id).owner == "Ирина"


# Проверяет, что после delete_pet карточку нельзя найти по идентификатору.
def test_delete_pet(registry, pet_details):
    pet = registry.add_pet(pet_details)

    registry.delete_pet(pet.id)

    with pytest.raises(PetNotFoundError):
        registry.get_pet(pet.id)


# Проверяет, что PetForm.load заполняет форму выбранной карточкой.
def test_pet_form_load(qt_app):
    form = PetForm()
    pet = Pet(
        id=1, name="Луна", species="Кошка", owner="Анна", breed="", birth_date=date(2024, 5, 12)
    )

    form.load(pet)

    assert form.name.text() == "Луна"
    assert form.birth_date.text() == "2024-05-12"
    assert form.save_button.text() == "Сохранить изменения"


# Проверяет, что PetForm.details собирает данные из полей формы.
def test_pet_form_details(qt_app, pet_details):
    form = PetForm()
    form.name.setText("Луна")
    form.species.setText("Кошка")
    form.owner.setText("Анна")
    form.birth_date.setText("2024-05-12")

    assert form.details() == pet_details


# Проверяет, что ActivityChart.update_counts выставляет значения семи столбцов.
def test_activity_chart_update_counts(qt_app):
    chart = ActivityChart()
    counts = [0, 1, 0, 3, 2, 0, 1]
    days = [date(2024, 5, 6) + timedelta(days=index) for index in range(7)]

    chart.update_counts(list(zip(days, counts)))

    series = chart.chart().series()[0]
    assert isinstance(series, QBarSeries)
    bars = series.barSets()[0]
    assert [bars.at(index) for index in range(bars.count())] == counts


# Проверяет преобразование данных веб-формы в карточку с датой рождения.
def test_web_form_to_details(pet_details):
    form = PetInput(name="Луна", species="Кошка", owner="Анна", birth_date="2024-05-12")

    assert form.to_details() == pet_details
