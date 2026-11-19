from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                              QHBoxLayout, QLineEdit, QPlainTextEdit, QScrollArea, QSpinBox,
                              QVBoxLayout, QWidget, QLabel)

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
        layout.setContentsMargins(0, 0, 8, 16)
        layout.setSpacing(16)
        layout.addWidget(label("Правила обработки", "title"))
        layout.addWidget(label("Настройки применяются при следующем запуске обработки.", "muted", True))

        geometry = QGroupBox("Геометрия и категория")
        form = self.form(geometry)
        self.mode = choices((("XY · в плане", "XY"), ("XYZ · с учётом RL", "XYZ")))
        self.unit = QLineEdit()
        self.unit.setPlaceholderText("Единицы исходных координат")
        self.category = choices((("Из выбранного столбца Excel", "source"),
                                 ("По полному положению относительно контура", "geometry")))
        form.addRow("Расчёт длины", self.mode)
        form.addRow("Единицы", self.unit)
        self.split = choices((("Разделять по границе контура", "contour"), ("Не разделять по границе руды", "whole")))
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
        form = self.form(identity)
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
        form.addRow(label("Все части одной исходной выработки получают общий номер. Суффикс P означает породу, R — руду.", "muted", True))
        layout.addWidget(identity)

        numbering = QGroupBox("Нумерация по настройкам проекта")
        form = self.form(numbering)
        self.numbering = QCheckBox("Рассчитать предварительные номера")
        self.number_unit = choices((("Целые линии на плане · один номер на всю линию", "axis"),
                                    ("Отдельные записи Excel · по исходному JOIN", "source"),
                                    ("Связанные Порода — Руда · общий номер пары осей", "linked")))
        self.number_unit_help = label("", "muted", True)
        self.line_orientation = choices((("Определить по преобладающим прямым", "auto"),
                                         ("Указать азимут линий", "manual")))
        self.line_bearing = real_spin(0,359.999)
        self.line_bearing.setValue(90)
        self.line_angle = real_spin(.01,30)
        self.line_angle.setValue(2)
        self.line_tolerance = real_spin(0,10000,6)
        self.line_tolerance.setValue(.01)
        self.line_orientation.currentIndexChanged.connect(self.update_line_controls)
        self.scope = choices((("Заново на каждом горизонте и рудном теле", "horizon"),
                              ("Непрерывно по каждому рудному телу", "body")))
        self.direction = choices((("С севера на юг · сверху вниз на плане", "north_south"),
                                  ("С юга на север · снизу вверх на плане", "south_north"),
                                  ("С запада на восток · слева направо", "west_east"),
                                  ("С востока на запад · справа налево", "east_west"),
                                  ("Сверху вниз · от верхних горизонтов к нижним", "top_bottom"),
                                  ("Снизу вверх · от нижних горизонтов к верхним", "bottom_top"),
                                  ("Своё направление или расстояние", "custom")))
        self.order = choices((("По проекции вдоль азимута", "projection"),
                              ("По расстоянию от точки", "distance")))
        self.category_priority = choices((("Положение", "position"), ("Сначала Порода", "P"), ("Сначала Руда", "R")))
        self.east = real_spin(-1e14, 1e14)
        self.north = real_spin(-1e14, 1e14)
        self.bearing = real_spin(0, 359.999)
        self.reverse = QCheckBox("Обратный порядок")
        self.first = QSpinBox()
        self.first.setRange(1, 99999999)
        self.pick = button("Указать точку на схеме", lambda: self.pick_requested.emit())
        origin = QHBoxLayout()
        origin.setSpacing(8)
        origin.addWidget(label("EAST"))
        origin.addWidget(self.east, 2)
        origin.addWidget(label("NORTH"))
        origin.addWidget(self.north, 2)
        origin.addWidget(self.pick)
        form.addRow(self.numbering)
        form.addRow("Что нумеровать", self.number_unit)
        form.addRow(self.number_unit_help)
        form.addRow("Направление самих линий", self.line_orientation)
        form.addRow("Азимут линий от NORTH, °", self.line_bearing)
        form.addRow("Отклонение от прямой, °", self.line_angle)
        form.addRow("Допуск стыковки, ед. координат", self.line_tolerance)
        form.addRow("Начинать счёт", self.scope)
        form.addRow("Направление", self.direction)
        form.addRow("Свой способ сортировки", self.order)
        form.addRow("Приоритет категории из Excel", self.category_priority)
        form.addRow("Точка отсчёта", origin)
        form.addRow("Азимут от NORTH по часовой, °", self.bearing)
        form.addRow("Первый номер", self.first)
        form.addRow(self.reverse)
        form.addRow(label("Для целых линий порядок определяется по центру линии, для записей Excel — по первой исходной точке. Север на плане находится сверху. «Сверху вниз по горизонтам» использует высоту RL. При одинаковой позиции порядок задают остальные координаты и исходная строка Excel. Все части оси сохраняют её номер.", "muted", True))
        self.number_unit.currentIndexChanged.connect(self.update_number_unit)
        self.update_number_unit()
        self.direction.currentIndexChanged.connect(self.update_direction)
        self.order.currentIndexChanged.connect(self.update_direction)
        self.update_direction()
        layout.addWidget(numbering)
        # Keep field columns aligned across all three rule groups.
        for form in contents.findChildren(QFormLayout):
            for row in range(form.rowCount()):
                item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                widget = item.widget() if item else None
                if isinstance(widget, QLabel):
                    widget.setFixedWidth(208)
                    widget.setWordWrap(True)
        layout.addStretch()
        self.setWidget(contents)

        for combo in (self.mode, self.category, self.order, self.category_priority, self.naming_style, self.split, self.links, self.scope, self.direction, self.number_unit, self.line_orientation):
            combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        for text in (self.unit, self.prefix, self.bodies, self.kind_code, self.kind_name):
            text.textChanged.connect(lambda *_: self.changed.emit())
        for spin in (self.digits, self.east, self.north, self.bearing, self.first, self.line_bearing, self.line_angle, self.line_tolerance):
            spin.valueChanged.connect(lambda *_: self.changed.emit())
        self.numbering.toggled.connect(lambda *_: self.changed.emit())
        self.reverse.toggled.connect(lambda *_: self.changed.emit())

    @staticmethod
    def form(parent):
        form = QFormLayout(parent)
        form.setContentsMargins(16, 16, 16, 16)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        return form

    def update_line_controls(self):
        active=self.number_unit.currentData()=="axis"
        self.line_orientation.setEnabled(active)
        self.line_bearing.setEnabled(active and self.line_orientation.currentData()=="manual")
        self.line_angle.setEnabled(active)
        self.line_tolerance.setEnabled(active)

    def update_number_unit(self):
        mode=self.number_unit.currentData()
        if mode == "axis":
            text = "Одна прямая линия на плане — один номер, общий для всех её частей Порода и Руда, даже при разных JOIN. Изогнутые переходы сохраняются, но не объединяют номера соседних линий. Нумерация не зависит от установления пар."
        elif mode == "source":
            text = "Каждая исходная запись JOIN получает свой номер. Одна запись Excel может содержать несколько линий и переход между ними. Этот режим сохраняет прежнюю нумерацию по данным Excel."
        else:
            text = "Две исходные записи с однозначной связью Порода — Руда получают общий номер. Используются пары из настройки «Связывание». Без однозначной пары записи нумеруются отдельно."
        self.number_unit_help.setText(text)
        self.update_line_controls()

    def update_direction(self):
        custom = self.direction.currentData() == "custom"
        self.order.setEnabled(custom)
        self.pick.setEnabled(custom)
        self.bearing.setEnabled(custom and self.order.currentData() == "projection")
        self.east.setEnabled(custom)
        self.north.setEnabled(custom)
        self.reverse.setToolTip("Переворачивает выбранное направление целиком.")
        self.category_priority.setToolTip("Сначала оси с выбранной категорией в Excel, затем остальные. Внутри каждой группы действует выбранное направление.")

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
            self.split.currentData(), self.links.currentData(),
            numbering_scope=self.scope.currentData(), direction=self.direction.currentData(),
            numbering_unit=self.number_unit.currentData(),
            line_angle=self.line_angle.value(), line_tolerance=self.line_tolerance.value(),
            line_azimuth=self.line_bearing.value() if self.line_orientation.currentData()=="manual" else None
        )

    def load_config(self, config):
        for combo, value in ((self.mode, config.length_mode), (self.category, config.classification),
                             (self.order, config.order_by), (self.category_priority, config.priority),
                             (self.naming_style, config.naming.style), (self.split, config.split_rule),
                             (self.links, config.link_rule), (self.scope, config.numbering_scope),
                             (self.direction, config.direction), (self.number_unit, config.numbering_unit)):
            combo.setCurrentIndex(combo.findData(value))
        self.line_orientation.setCurrentIndex(self.line_orientation.findData("auto" if config.line_azimuth is None else "manual"))
        self.line_bearing.setValue(config.line_azimuth if config.line_azimuth is not None else 90)
        self.line_angle.setValue(config.line_angle)
        self.line_tolerance.setValue(config.line_tolerance)
        self.update_line_controls()
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

