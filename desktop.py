import sys
from datetime import date
from pathlib import Path

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QValueAxis
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QKeySequence, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import URL

from pet_registry.models import Pet, PetDetails, RegistryError, parse_birth_date
from pet_registry.storage import PetRegistry


def make_table(headers: tuple[str, ...]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.verticalHeader().hide()
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return table


def fill_table(table: QTableWidget, rows: list[tuple[str, ...]]) -> None:
    table.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            table.setItem(row, column, item)


class PetForm(QGroupBox):
    def __init__(self) -> None:
        super().__init__("Новая карточка")
        layout = QFormLayout(self)
        self.name = QLineEdit()
        self.species = QLineEdit()
        self.owner = QLineEdit()
        self.breed = QLineEdit()
        for label, field in (
            ("Кличка *", self.name),
            ("Вид *", self.species),
            ("Владелец *", self.owner),
            ("Порода", self.breed),
        ):
            layout.addRow(label, field)

        self.birth_date = QLineEdit()
        self.birth_date.setPlaceholderText("ГГГГ-ММ-ДД")
        layout.addRow("Дата рождения", self.birth_date)
        layout.addRow(QLabel("* Обязательные поля"))

        self.save_button = QPushButton()
        self.new_button = QPushButton("Новая карточка")
        self.delete_button = QPushButton("Удалить")
        actions = QHBoxLayout()
        actions.addWidget(self.new_button)
        actions.addWidget(self.delete_button)
        layout.addRow(self.save_button)
        layout.addRow(actions)
        self.load(None)

    def load(self, pet: Pet | None) -> None:
        self.setTitle(f"Карточка №{pet.id}" if pet else "Новая карточка")
        self.name.setText(pet.name if pet else "")
        self.species.setText(pet.species if pet else "")
        self.owner.setText(pet.owner if pet else "")
        self.breed.setText(pet.breed if pet else "")
        self.birth_date.setText(pet.birth_date.isoformat() if pet and pet.birth_date else "")
        self.save_button.setText("Сохранить изменения" if pet else "Добавить питомца")
        self.new_button.setEnabled(pet is not None)
        self.delete_button.setEnabled(pet is not None)

    def details(self) -> PetDetails:
        return PetDetails(
            name=self.name.text(),
            species=self.species.text(),
            owner=self.owner.text(),
            breed=self.breed.text(),
            birth_date=parse_birth_date(self.birth_date.text()),
        )


class ActivityChart(QChartView):
    def __init__(self) -> None:
        chart = QChart()
        super().__init__(chart)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumHeight(230)

        self._bars = QBarSet("Операции")
        self._bars.append([0.0] * 7)
        series = QBarSeries()
        series.append(self._bars)
        chart.addSeries(series)
        chart.legend().hide()

        self._dates = QBarCategoryAxis()
        self._counts = QValueAxis()
        self._counts.setLabelFormat("%d")
        chart.addAxis(self._dates, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(self._counts, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(self._dates)
        series.attachAxis(self._counts)

    def update_counts(self, daily_counts: list[tuple[date, int]]) -> None:
        self._dates.clear()
        self._dates.append([day.strftime("%d.%m") for day, _ in daily_counts])
        for index, (_, count) in enumerate(daily_counts):
            self._bars.replace(index, count)

        maximum = max(1, max(count for _, count in daily_counts))
        step = (maximum + 3) // 4
        intervals = (maximum + step - 1) // step
        self._counts.setRange(0, step * intervals)
        self._counts.setTickCount(intervals + 1)


class MainWindow(QMainWindow):
    def __init__(self, registry: PetRegistry) -> None:
        super().__init__()
        self._registry = registry
        self._pets: list[Pet] = []
        self.setWindowTitle("Реестр питомцев")
        self.resize(1040, 680)

        file_menu = self.menuBar().addMenu("Файл")
        refresh = file_menu.addAction("Обновить")
        refresh.setShortcut(QKeySequence.StandardKey.Refresh)
        refresh.triggered.connect(self.refresh)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Выход")
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)

        tabs = QTabWidget()
        tabs.addTab(self._pets_page(), "Питомцы")
        tabs.addTab(self._activity_page(), "Активность")
        help_button = QPushButton("Справка")
        help_button.clicked.connect(self._show_help)
        tabs.setCornerWidget(help_button, Qt.Corner.TopRightCorner)
        self.setCentralWidget(tabs)
        self.refresh()

    def _pets_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._pet_summary = QLabel()
        layout.addWidget(self._pet_summary)

        content = QHBoxLayout()
        self._pet_table = make_table(("№", "Кличка", "Вид", "Владелец", "Порода", "Дата рождения"))
        self._pet_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._pet_table.itemSelectionChanged.connect(self._load_selection)
        content.addWidget(self._pet_table, 1)

        self._form = PetForm()
        self._form.save_button.clicked.connect(self._save_pet)
        self._form.new_button.clicked.connect(self._start_new_pet)
        self._form.delete_button.clicked.connect(self._delete_pet)
        content.addWidget(self._form, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(content, 1)
        return page

    def _activity_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Операции за последние 7 дней (UTC)"))
        self._chart = ActivityChart()
        layout.addWidget(self._chart, 1)
        layout.addWidget(QLabel("Журнал активности · до 50 последних операций"))
        self._log_table = make_table(("Время (UTC)", "Операция", "№ питомца", "Кличка"))
        layout.addWidget(self._log_table, 1)
        return page

    def refresh(self) -> None:
        try:
            pets = self._registry.list_pets()
            activity = self._registry.recent_activity()
            daily_counts = self._registry.daily_activity()
        except RegistryError as error:
            self._show_error(error)
            return

        self._pets = pets
        with QSignalBlocker(self._pet_table):
            self._pet_table.clearSelection()
            fill_table(self._pet_table, [
                (str(pet.id), pet.name, pet.species, pet.owner, pet.breed or "—",
                 pet.birth_date.strftime("%d.%m.%Y") if pet.birth_date else "—")
                for pet in pets
            ])
        self._load_selection()
        self._pet_summary.setText(
            f"Карточек: {len(pets)} · Выберите строку, чтобы изменить данные."
            if pets else "Карточек пока нет. Добавьте первого питомца через форму."
        )
        fill_table(self._log_table, [
            (event.occurred_at.strftime("%d.%m.%Y %H:%M:%S"), event.kind.value,
             str(event.pet_id), event.pet_name)
            for event in activity
        ])
        self._chart.update_counts(daily_counts)

    def _selected_pet(self) -> Pet | None:
        rows = self._pet_table.selectionModel().selectedRows()
        return self._pets[rows[0].row()] if rows else None

    def _load_selection(self) -> None:
        self._form.load(self._selected_pet())

    def _start_new_pet(self) -> None:
        with QSignalBlocker(self._pet_table):
            self._pet_table.clearSelection()
        self._form.load(None)
        self._form.name.setFocus()

    def _save_pet(self) -> None:
        pet = self._selected_pet()
        try:
            details = self._form.details()
            if pet is None:
                self._registry.add_pet(details)
            else:
                self._registry.update_pet(pet.id, details)
        except RegistryError as error:
            self._show_error(error)
            return

        self._start_new_pet()
        self.statusBar().showMessage("Карточка сохранена.", 4000)
        self.refresh()

    def _delete_pet(self) -> None:
        pet = self._selected_pet()
        if pet is None:
            return
        dialog = QMessageBox(parent=self)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle("Удаление карточки")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f"Удалить карточку питомца «{pet.name}»?")
        confirm = dialog.addButton("Удалить", QMessageBox.ButtonRole.DestructiveRole)
        cancel = dialog.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        confirmed = dialog.clickedButton() == confirm
        dialog.deleteLater()
        if not confirmed:
            return

        try:
            self._registry.delete_pet(pet.id)
        except RegistryError as error:
            self._show_error(error)
            return

        self._start_new_pet()
        self.statusBar().showMessage("Карточка удалена.", 4000)
        self.refresh()

    def _show_error(self, error: RegistryError) -> None:
        QMessageBox.warning(self, "Реестр питомцев", str(error))

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "Справка",
            "Заполните кличку, вид и владельца, затем нажмите «Добавить питомца». "
            "Дату рождения можно указать в формате ГГГГ-ММ-ДД.\n\n"
            "Для правки или удаления выберите строку в таблице и нажмите "
            "«Сохранить изменения» или «Удалить».\n\n"
            "Журнал и график за семь дней находятся на вкладке «Активность».",
        )


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Реестр питомцев")
    database_path = Path(__file__).resolve().with_name("pets.sqlite3")
    try:
        registry = PetRegistry(URL.create("sqlite", database=str(database_path)))
    except RegistryError as error:
        QMessageBox.critical(None, "Реестр питомцев", str(error))
        return 1

    try:
        window = MainWindow(registry)
        window.show()
        return app.exec()
    finally:
        registry.close()


if __name__ == "__main__":
    sys.exit(main())
