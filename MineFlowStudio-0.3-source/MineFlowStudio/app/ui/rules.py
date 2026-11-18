from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                              QHBoxLayout, QLineEdit, QPlainTextEdit, QScrollArea, QSpinBox,
                              QVBoxLayout, QWidget)

from app.ui.widgets import button, label
from domain.models import NamingRule, OreBody, ProcessingConfig


def choices(items):
    combo = QComboBox()
    for text, value in items:
        combo.addItem(text, value)
    return combo


def real_spin(minimum, maximum, decimals=3):
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(decimals)
    spin.setKeyboardTracking(False)
    return spin


class RulePanel(QScrollArea):
    pick_requested = Signal()
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        contents = QWidget()
        layout = QVBoxLayout(contents)
        layout.setContentsMargins(1, 1, 10, 12)
        layout.setSpacing(12)
        layout.addWidget(label("Правила обработки", "title"))
        layout.addWidget(label("Настройки применяются при следующем запуске обработки.", "muted", True))

        geometry = QGroupBox("Геометрия и категория")
        form = QFormLayout(geometry)
        self.mode = choices((("XY · в плане", "XY"), ("XYZ · с учётом RL", "XYZ")))
        self.unit = QLineEdit()
        self.unit.setPlaceholderText("Единицы исходных координат")
        self.category = choices((("Из выбранного столбца Excel", "source"),
                                 ("По полному положению относительно контура", "geometry")))
        form.addRow("Расчёт длины", self.mode)
        form.addRow("Единицы", self.unit)
        self.split = choices((("Разделять по границе контура", "contour"), ("Сохранять ось целиком", "whole")))
        self.links = choices((("Непрерывность и один партнёр", "continuity"), ("Явный ID пары из Excel", "explicit"),
                              ("Связи отключены", "none")))
        form.addRow("Разделение", self.split)
        form.addRow("Категория целой оси", self.category)
        form.addRow("Связывание", self.links)
        form.addRow(label("Участки на границе и неоднозначные пары попадают в список для подтверждения.", "muted", True))
        self.split.currentIndexChanged.connect(self.update_categories)
        self.update_categories()
        layout.addWidget(geometry)

        identity = QGroupBox("Рудные тела и маркировка")
        form = QFormLayout(identity)
        self.bodies = QPlainTextEdit()
        self.bodies.setFixedHeight(88)
        self.bodies.setPlaceholderText("Название из Excel = маркировка")
        self.prefix = QLineEdit("MF")
        self.prefix.setMaxLength(24)
        self.digits = QSpinBox()
        self.digits.setRange(1, 8)
        self.digits.setValue(2)
        form.addRow("Тела (по одному на строку)", self.bodies)
        self.naming_style = choices((("Внутренняя маркировка MineFlow", "internal"),
                                     ("Шаблон 350_5_N_OBD_P", "case")))
        self.kind_code = QLineEdit()
        self.kind_code.setPlaceholderText("Код типа для выбранной области")
        self.kind_name = QLineEdit()
        self.kind_name.setPlaceholderText("Название типа для выбранной области")
        form.addRow("Формат маркировки", self.naming_style)
        form.addRow("Маркировка MineFlow", self.prefix)
        form.addRow("Разрядность номера MineFlow", self.digits)
        form.addRow("Код типа для шаблона кейса", self.kind_code)
        form.addRow("Название типа", self.kind_name)
        form.addRow(label("Шаблон кейса использует CODE из Excel и заданный вами тип. Применяйте его к однородной выборке.", "muted", True))
        form.addRow(label("У однозначной пары один номер и разные суффиксы. Шаблон кейса требует кода типа.", "muted", True))
        layout.addWidget(identity)

        numbering = QGroupBox("Нумерация по настройкам проекта")
        form = QFormLayout(numbering)
        self.numbering = QCheckBox("Рассчитать предварительные номера")
        self.order = choices((("По проекции вдоль азимута", "projection"),
                              ("По расстоянию от точки", "distance")))
        self.category_priority = choices((("Положение", "position"), ("Сначала Порода", "P"), ("Сначала Руда", "R")))
        self.east = real_spin(-1e14, 1e14)
        self.north = real_spin(-1e14, 1e14)
        self.bearing = real_spin(0, 359.999)
        self.reverse = QCheckBox("Обратный порядок")
        self.first = QSpinBox()
        self.first.setRange(1, 99999999)
        pick = button("Указать точку на схеме", lambda: self.pick_requested.emit())
        origin = QHBoxLayout()
        origin.addWidget(label("EAST"))
        origin.addWidget(self.east, 2)
        origin.addWidget(label("NORTH"))
        origin.addWidget(self.north, 2)
        origin.addWidget(pick)
        form.addRow(self.numbering)
        form.addRow("Сортировка", self.order)
        form.addRow("Приоритет", self.category_priority)
        form.addRow("Точка отсчёта", origin)
        form.addRow("Азимут от NORTH по часовой, °", self.bearing)
        form.addRow("Первый номер", self.first)
        form.addRow(self.reverse)
        form.addRow(label("Позиция — первая точка группы. Счёт начинается заново для каждого горизонта и тела.", "muted", True))
        layout.addWidget(numbering)
        layout.addStretch()
        self.setWidget(contents)

        for combo in (self.mode, self.category, self.order, self.category_priority, self.naming_style, self.split, self.links):
            combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        for text in (self.unit, self.prefix, self.bodies, self.kind_code, self.kind_name):
            text.textChanged.connect(lambda *_: self.changed.emit())
        for spin in (self.digits, self.east, self.north, self.bearing, self.first):
            spin.valueChanged.connect(lambda *_: self.changed.emit())
        self.numbering.toggled.connect(lambda *_: self.changed.emit())
        self.reverse.toggled.connect(lambda *_: self.changed.emit())

    def update_categories(self):
        self.category.setEnabled(self.split.currentData() == "whole")

    def config(self, working, contour):
        bodies = []
        for line in self.bodies.toPlainText().splitlines():
            if not line.strip():
                continue
            name, sep, mark = line.partition("=")
            mark = mark.strip() if sep else name.strip()
            if not name.strip() or not mark:
                raise ValueError("Введите название и маркировку каждого рудного тела.")
            bodies.append(OreBody(name.strip(), mark))
        return ProcessingConfig(
            working, contour, tuple(bodies), NamingRule(
                self.prefix.text().strip(), self.digits.value(), self.naming_style.currentData(),
                self.kind_code.text().strip(), self.kind_name.text().strip()),
            self.mode.currentData(), self.unit.text().strip(), self.category.currentData(),
            self.numbering.isChecked(), self.order.currentData(), self.east.value(), self.north.value(),
            self.bearing.value(), self.reverse.isChecked(), self.category_priority.currentData(), self.first.value(),
            self.split.currentData(), self.links.currentData()
        )

    def load_config(self, config):
        for combo, value in ((self.mode, config.length_mode), (self.category, config.classification),
                             (self.order, config.order_by), (self.category_priority, config.priority),
                             (self.naming_style, config.naming.style), (self.split, config.split_rule),
                             (self.links, config.link_rule)):
            combo.setCurrentIndex(combo.findData(value))
        self.unit.setText(config.unit)
        self.bodies.setPlainText("\n".join(f"{body.name} = {body.mark}" for body in config.bodies))
        self.prefix.setText(config.naming.prefix)
        self.kind_code.setText(config.naming.kind_code)
        self.kind_name.setText(config.naming.kind_name)
        self.digits.setValue(config.naming.digits)
        self.numbering.setChecked(config.numbering)
        self.east.setValue(config.start_east)
        self.north.setValue(config.start_north)
        self.bearing.setValue(config.bearing)
        self.reverse.setChecked(config.reverse)
        self.first.setValue(config.first)

