from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                              QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from app.ui.widgets import label, table
from domain.models import ColumnMap
from services.importer import header_value, suggest

FIELDS = {
    "east": "EAST · X",
    "north": "NORTH · Y",
    "rl": "RL · Z",
    "group": "Идентификатор группы",
    "horizon": "Горизонт (резерв — RL)",
    "body": "Название рудного тела",
    "category": "Категория Порода / Руда",
    "order": "Порядок точек",
    "pair": "Явный идентификатор пары",
    "input_length": "Длина из Excel",
    "code": "Код CODE для маркировки",
}


class MappingTab(QWidget):
    def __init__(self, source, selected, allow_empty=False):
        super().__init__()
        self.source = source
        self.allow_empty = allow_empty
        self.sheet = QComboBox()
        if allow_empty:
            self.sheet.addItem("Без листа контуров", None)
        for sheet in source.sheets:
            self.sheet.addItem(sheet.title, sheet.title)
        if selected:
            self.sheet.setCurrentIndex(self.sheet.findData(selected.sheet))
        self.header = QSpinBox()
        self.header.setRange(1, 1048576)
        self.header.setValue(selected.header if selected else 1)
        bar = QHBoxLayout()
        bar.addWidget(label("Лист"))
        bar.addWidget(self.sheet, 4)
        bar.addWidget(label("Строка заголовков"))
        bar.addWidget(self.header)

        self.form = QWidget()
        form = QFormLayout(self.form)
        self.columns = {}
        for name, title in FIELDS.items():
            combo = QComboBox()
            combo.setMinimumContentsLength(18)
            form.addRow(title, combo)
            self.columns[name] = combo
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setWidget(self.form)
        self.preview, self.preview_rows, _ = table(self)
        self.preview.setSortingEnabled(False)
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(scroller, 4)
        layout.addWidget(label("Предпросмотр исходного листа", "section"))
        layout.addWidget(self.preview, 2)
        self.sheet.currentIndexChanged.connect(self.reset_columns)
        self.header.valueChanged.connect(self.reset_columns)
        self.reset_columns(selected=selected)

    def reset_columns(self, _value=None, selected=None):
        title = self.sheet.currentData()
        self.form.setEnabled(title is not None)
        self.header.setEnabled(title is not None)
        if title is None:
            self.preview_rows.reset()
            return
        sheet = self.source.sheet(title)
        row = self.header.value()
        mapping = selected or suggest(sheet, row)
        width = max((len(values) for values in sheet.rows), default=0)
        headers = tuple(header_value(sheet, row, i) for i in range(width))
        self.preview_rows.reset(headers, sheet.rows[row:row + 8])
        for key, combo in self.columns.items():
            combo.clear()
            combo.addItem("Не сопоставлено", None)
            for i, heading in enumerate(headers):
                combo.addItem(heading, i)
            combo.setCurrentIndex(max(0, combo.findData(getattr(mapping, key))))

    def value(self):
        title = self.sheet.currentData()
        if title is None:
            return None
        return ColumnMap(title, self.header.value(),
                         **{key: item.currentData() for key, item in self.columns.items()})


class MappingDialog(QDialog):
    def __init__(self, parent, source, working, contour):
        super().__init__(parent)
        self.setWindowTitle("Листы и столбцы · MineFlow Studio")
        self.resize(820, 650)
        self.tabs = QTabWidget()
        self.working = MappingTab(source, working)
        self.contour = MappingTab(source, contour, allow_empty=True)
        self.tabs.addTab(self.working, "Выработки")
        self.tabs.addTab(self.contour, "Контуры")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Применить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.validate_selection)
        buttons.rejected.connect(self.reject)
        self.warning = label("", "warning", True)
        layout = QVBoxLayout(self)
        layout.addWidget(label("Сопоставление столбцов", "title"))
        layout.addWidget(label("Проверьте назначение полей. Без столбца порядка используются строки Excel.", "muted", True))
        layout.addWidget(self.tabs)
        layout.addWidget(self.warning)
        layout.addWidget(buttons)

    def validate_selection(self):
        working, contour = self.working.value(), self.contour.value()
        if contour and working.sheet == contour.sheet:
            self.warning.setText("Для выработок и контуров укажите разные листы.")
            return
        for mapping in (working, contour):
            if mapping is not None and (mapping.east is None or mapping.north is None or mapping.group is None
                                        or mapping.east == mapping.north):
                self.warning.setText(f"На листе «{mapping.sheet}» укажите EAST, NORTH и группу.")
                return
        self.accept()

