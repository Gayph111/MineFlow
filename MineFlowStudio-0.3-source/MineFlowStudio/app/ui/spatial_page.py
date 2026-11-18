from collections import defaultdict

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLineEdit,
                              QScrollArea, QSplitter, QStyle, QTreeWidget, QTreeWidgetItem,
                              QVBoxLayout, QWidget)

from app.ui.vtk_scene import STEEL, VtkScene, WARNING
from app.ui.style import ERROR, ORE, PRIMARY
from app.ui.widgets import button, label, selected_key, table
from services.spatial_model import build_spatial_model

ID_ROLE = Qt.ItemDataRole.UserRole
SCOPE_ROLE = Qt.ItemDataRole.UserRole + 1
CHECKED = Qt.CheckState.Checked

HEADERS = ("ID", "JOIN", "Горизонт", "Рудное тело", "Длина", "Номер", "Маркировка", "Положение")


class SpatialPage(QWidget):
    selected = Signal(str)
    show_plan = Signal()
    source_rows = Signal(str)
    full_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self.by_id = {}
        self.ids_in_tree = {}
        self.geometry = ((), ())
        self.row_for = {}
        self.audit_fails = set()
        self.audit_unknown = set()
        self.advisories = set()
        self.base_errors = set()
        self.current = ""
        self.full = False
        self.syncing = False
        self.scene = VtkScene(self)
        self.scene.object_picked.connect(self.select)
        self.build_ui()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        main_bar = QHBoxLayout()
        main_bar.addWidget(label("Пространственная модель", "title"))
        main_bar.addStretch()
        main_bar.addWidget(button("План 2D", lambda: self.show_plan.emit()))
        self.full_button = button("На весь экран", lambda: self.full_requested.emit())
        self.full_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton))
        main_bar.addWidget(self.full_button)
        layout.addLayout(main_bar)
        toolset = QHBoxLayout()
        for name, command in (("Изометрия", self.default_view), ("Сверху", self.scene.view_xy),
                              ("Спереди", self.scene.view_xz), ("Сбоку", self.scene.view_yz),
                              ("Вписать", self.scene.fit_all), ("К объекту", self.center_selected)):
            control = button(name, lambda _checked=False, action=command: action())
            toolset.addWidget(control)
        self.parallel = button("Ортографическая", self.toggle_projection)
        self.parallel.setCheckable(True)
        self.parallel.setChecked(True)
        toolset.addWidget(self.parallel)
        toolset.addStretch()
        self.show_grid = QCheckBox("Сетка")
        self.show_grid.setChecked(True)
        self.show_grid.toggled.connect(self.toggle_grid)
        toolset.addWidget(self.show_grid)
        layout.addLayout(toolset)

        self.side = QSplitter(Qt.Orientation.Horizontal)
        self.tree_panel = self.build_tree_panel()
        self.side.addWidget(self.tree_panel)
        self.side.addWidget(self.scene)
        self.right_panel = self.build_properties()
        self.side.addWidget(self.right_panel)
        self.side.setStretchFactor(1, 1)
        self.side.setSizes([225, 650, 260])
        for i in range(3):
            self.side.setCollapsible(i, False)

        self.vertical = QSplitter(Qt.Orientation.Vertical)
        self.vertical.addWidget(self.side)
        self.table_panel = self.build_table()
        self.vertical.addWidget(self.table_panel)
        self.vertical.setSizes([600, 160])
        self.vertical.setStretchFactor(0, 1)
        self.vertical.setCollapsible(0, False)
        layout.addWidget(self.vertical, 1)
        self.layer_bar = QHBoxLayout()
        self.toggles = {}
        for title, key in (("Контуры", "outline"), ("Связи", "links"), ("Обозначения", "labels"), ("Замечания", "issues")):
            check = QCheckBox(title)
            check.setChecked(True)
            check.toggled.connect(self.apply_filters)
            self.toggles[key] = check
            self.layer_bar.addWidget(check)
        self.layer_bar.addStretch()
        for title, color in (("Порода", PRIMARY), ("Руда и контуры", ORE), ("Без категории", STEEL),
                             ("Проверить", WARNING), ("Ошибка", ERROR)):
            item = label("● " + title)
            item.setStyleSheet(f"color: {color};")
            self.layer_bar.addWidget(item)
        layout.addLayout(self.layer_bar)

    def build_tree_panel(self):
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setMinimumWidth(190)
        panel.setMaximumWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(11, 10, 11, 9)
        layout.addWidget(label("Объекты", "section"))
        self.query = QLineEdit()
        self.query.setPlaceholderText("ID, JOIN или обозначение")
        self.query.textChanged.connect(self.apply_filters)
        layout.addWidget(self.query)
        self.body_filter = QComboBox()
        self.body_filter.setMinimumContentsLength(12)
        self.body_filter.currentIndexChanged.connect(self.apply_filters)
        layout.addWidget(self.body_filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(13)
        self.tree.setUniformRowHeights(True)
        self.tree.setStyleSheet("QTreeWidget { background: #141E29; border: 1px solid #344454; border-radius: 7px; }"
                                "QTreeWidget::item { height: 25px; }"
                                "QTreeWidget::item:selected { background: #255479; }")
        self.tree.itemChanged.connect(self.scope_changed)
        self.tree.currentItemChanged.connect(self.tree_selection)
        layout.addWidget(self.tree, 1)
        self.scene_count = label("", "muted", True)
        layout.addWidget(self.scene_count)
        return panel

    def build_properties(self):
        frame = QFrame()
        frame.setObjectName("panel")
        frame.setMinimumWidth(214)
        frame.setMaximumWidth(347)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(11, 10, 11, 8)
        layout.addWidget(label("Характеристики", "section"))
        self.caption = label("Выберите ось или строку.", "muted", True)
        layout.addWidget(self.caption)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(0, 0, 0, 0)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.properties = {}
        for title in ("JOIN", "Горизонт", "Рудное тело", "Начало XYZ", "Длина", "Категория", "Положение",
                      "Номер", "Обозначение", "Название", "Основание", "Исходная ось", "Связь", "Источник", "Проверка"):
            value = label("—", wrap=True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(label(title, "muted"), value)
            self.properties[title] = value
        scroll.setWidget(box)
        layout.addWidget(scroll, 1)
        self.open_source = button("Исходные строки", lambda: self.source_rows.emit(self.current))
        self.open_source.setEnabled(False)
        layout.addWidget(self.open_source)
        return frame

    def build_table(self):
        panel = QFrame()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.footer = label("Обработанные группы", "muted")
        layout.addWidget(self.footer)
        self.result_table, self.result_model, self.result_proxy = table(panel)
        self.result_table.setMinimumHeight(70)
        self.result_table.selectionModel().currentChanged.connect(self.row_selection)
        self.result_table.doubleClicked.connect(lambda _index: self.center_selected())
        layout.addWidget(self.result_table, 1)
        return panel

    def set_result(self, result, current=""):
        previous_geometry = self.geometry
        self.result = result
        self.geometry = build_spatial_model(result)
        self.by_id = {item.id: item for item in result.excavations}
        self.shapes = {item.id: item for item in self.geometry[0]}
        by_ref = {ref: e.id for e in result.excavations for ref in e.refs}
        self.base_errors = {by_ref[ref] for finding in result.issues if finding.severity == "Ошибка"
                            for ref in finding.refs if ref in by_ref}
        self.advisories = {by_ref[ref] for finding in result.issues
                           if finding.code in {"contour_copy", "closed_working", "contour_match"}
                           for ref in finding.refs if ref in by_ref}
        self.advisories.update(e.id for e in result.excavations if e.review)
        self.audit_fails.clear()
        self.audit_unknown.clear()
        self.current = current if current in self.by_id else ""
        self.load_tree()
        self.load_rows()
        self.apply_filters(reset=previous_geometry != self.geometry)

    def load_tree(self):
        previous_filter = self.body_filter.currentData()
        previous = {item.data(0, SCOPE_ROLE): item.checkState(0)
                    for item in self.scope_items()} if self.tree.topLevelItemCount() else {}
        selected = defaultdict(lambda: defaultdict(list))
        for shape, item in zip(self.geometry[0], self.result.excavations):
            selected[shape.body][shape.horizon].append(item)
        for shape in self.geometry[1]:
            selected[shape.body][shape.horizon]
        self.tree.blockSignals(True)
        self.body_filter.blockSignals(True)
        self.tree.clear()
        self.ids_in_tree.clear()
        self.body_filter.clear()
        self.body_filter.addItem("Все рудные тела", None)
        for body, levels in sorted(selected.items()):
            body_label = body or "Тело не назначено"
            self.body_filter.addItem(body_label, body)
            parent = QTreeWidgetItem(self.tree, [body_label])
            parent.setExpanded(True)
            for level, objects in sorted(levels.items(), key=lambda pair: self.horizon_rank(pair[0]), reverse=True):
                branch = QTreeWidgetItem(parent, [f"{level or 'Без горизонта'}  ·  {len(objects)}"])
                branch.setFlags(branch.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                branch.setData(0, SCOPE_ROLE, (body, level))
                branch.setCheckState(0, previous.get((body, level), CHECKED))
                branch.setExpanded(not self.ids_in_tree and len(self.by_id) <= 200)
                for item in objects:
                    node = QTreeWidgetItem(branch, [self.item_text(item)])
                    node.setData(0, ID_ROLE, item.id)
                    self.ids_in_tree[item.id] = node
        self.body_filter.setCurrentIndex(max(0, self.body_filter.findData(previous_filter)))
        self.body_filter.blockSignals(False)
        self.tree.blockSignals(False)

    @staticmethod
    def horizon_rank(level):
        try:
            return 1, float(level)
        except ValueError:
            return 0, level

    def scope_items(self):
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                yield parent.child(j)

    def item_text(self, item):
        return f"{item.group}  ·  {item.display_mark or item.id}"

    def load_rows(self):
        self.syncing = True
        self.row_for = {e.id: i for i, e in enumerate(self.result.excavations)}
        self.result_model.reset(HEADERS, ((e.id, e.group, e.horizon, e.body,
                                        round(e.length, 6) if e.length is not None else None,
                                        e.display_number, e.display_mark, e.spatial) for e in self.result.excavations),
                                self.row_for.keys(), [self.row_for[k] for k in self.base_errors | self.audit_fails])
        self.result_table.setColumnWidth(6, 220)
        self.result_table.setColumnWidth(7, 155)
        self.syncing = False



    def scope_changed(self, item, column):
        if column == 0 and item.data(0, SCOPE_ROLE) is not None:
            self.apply_filters()

    def apply_filters(self, *_, reset=False):
        if self.result is None:
            return
        body = self.body_filter.currentData()
        chosen_scopes = {tuple(item.data(0, SCOPE_ROLE)) for item in self.scope_items()
                         if item.checkState(0) == CHECKED}
        search = self.query.text().strip().casefold()
        visible = set()
        self.tree.blockSignals(True)
        alerts = self.advisories | self.audit_unknown
        errors = self.base_errors | self.audit_fails
        for e in self.result.excavations:
            active_body = body in (None, e.body)
            matches = not search or search in " ".join((e.id, e.group, e.display_mark, e.display_name, e.horizon, e.body)).casefold()
            node = self.ids_in_tree[e.id]
            node.setHidden(not (active_body and matches))
            check = (e.body, e.horizon) in chosen_scopes
            if active_body and matches and check:
                visible.add(e.id)
            color = ERROR if e.id in errors else WARNING if e.id in alerts else "#EAF0F6"
            node.setForeground(0, QBrush(QColor(color)))
        for i in range(self.tree.topLevelItemCount()):
            node = self.tree.topLevelItem(i)
            node.setHidden(body not in (None, "" if node.text(0) == "Тело не назначено" else node.text(0)))
        self.tree.blockSignals(False)
        self.syncing = True
        self.result_proxy.set_restriction(visible)
        self.syncing = False
        checked = lambda field: self.toggles[field].isChecked()
        outlines = [(shape, c.valid) for shape, c in zip(self.geometry[1], self.result.contours)
                    if checked("outline") and body in (None, shape.body)
                    and (shape.body, shape.horizon) in chosen_scopes]
        visible_axes = [(shape, self.by_id[shape.id]) for shape in self.geometry[0] if shape.id in visible]
        self.scene.labels = checked("labels")
        labels = [(e.id, e.display_mark, e.display_number) for _, e in visible_axes if e.display_mark]
        use_compact = len(labels) > 8
        self.scene.draw(visible_axes, outlines, {key: str(number) if use_compact and number is not None else mark
                                                for key, mark, number in labels},
                        alerts if checked("issues") else set(), errors if checked("issues") else set(),
                        checked("links"), reset=reset)
        affected = sum(shape.unplaced for shape, _ in [*visible_axes, *outlines])
        self.scene_count.setText(f"{len(visible_axes)} из {len(self.by_id)} групп · {len(outlines)} контуров"
                                 + (f"\n{affected} точек без RL" if affected else ""))
        unit = self.result.config.unit or "единицы координат требуют подтверждения"
        subject = "Рабочие участки" if any(item.axis_id for item in self.by_id.values()) else "Исходные оси"
        self.footer.setText(f"{subject} · {self.result.config.length_mode} · {unit}")
        self.set_selection(self.current)

    def tree_selection(self, current, previous):
        if self.syncing or current is None:
            return
        item_id = current.data(0, ID_ROLE)
        if item_id:
            self.select(item_id)

    def row_selection(self, current, previous):
        if not self.syncing:
            item_id = selected_key(current, self.result_model, self.result_proxy)
            if item_id:
                self.select(item_id)

    def select(self, item_id):
        if item_id in self.by_id:
            self.set_selection(item_id)
            self.selected.emit(item_id)

    def reveal(self, item_id):
        node = self.ids_in_tree.get(item_id)
        if node is None:
            return
        item = self.by_id[item_id]
        self.syncing = True
        self.body_filter.blockSignals(True)
        self.query.blockSignals(True)
        self.tree.blockSignals(True)
        if self.body_filter.currentData() not in (None, item.body):
            self.body_filter.setCurrentIndex(0)
        self.query.clear()
        node.parent().setCheckState(0, CHECKED)
        self.body_filter.blockSignals(False)
        self.query.blockSignals(False)
        self.tree.blockSignals(False)
        self.syncing = False
        self.apply_filters()

    def set_selection(self, item_id, center=False):
        self.current = item_id
        item = self.by_id.get(item_id)
        self.syncing = True
        if item:
            node = self.ids_in_tree[item_id]
            if not node.isHidden() and not node.parent().parent().isHidden():
                node.parent().setExpanded(True)
                self.tree.setCurrentItem(node)
                self.tree.scrollToItem(node)
            index = self.result_proxy.mapFromSource(self.result_model.index(self.row_for[item_id], 0))
            if index.isValid():
                self.result_table.setCurrentIndex(index)
                self.result_table.scrollTo(index)
        else:
            self.tree.setCurrentItem(None)
            self.result_table.clearSelection()
        self.syncing = False
        self.scene.highlight(item_id, item.related if item else (), center=center)
        self.show_properties(item)

    def show_properties(self, item):
        self.caption.setText(item.id if item else "Выберите ось или строку.")
        self.open_source.setEnabled(item is not None)
        values = {}
        if item:
            point = item.anchor
            if item.id in self.audit_fails:
                test = "FAIL"
            elif item.review:
                test = item.review
            elif item.axis_id or item.id in self.audit_unknown:
                test = "UNVERIFIED"
            else:
                test = "Есть замечания" if item.id in self.base_errors | self.advisories else "—"
            values = {"JOIN": item.group, "Горизонт": item.horizon, "Рудное тело": item.body,
                      "Начало XYZ": (f"{point.east:.5f} / {point.north:.5f} / "
                                     + (f"{point.rl:.5f}" if point.rl is not None else "—") if point else "—"),
                      "Длина": f"{item.length:.6f}" if item.length is not None else "—",
                      "Категория": {"P": "Порода", "R": "Руда"}.get(item.category, "Не установлена"),
                      "Положение": item.spatial, "Номер": item.display_number, "Обозначение": item.display_mark,
                      "Название": item.display_name,
                      "Основание": "По настройкам" if item.axis_id and item.mark else item.designation_basis,
                      "Исходная ось": item.axis_id, "Связь": ", ".join(item.related) or item.pair,
                      "Источник": f"{item.refs[0].sheet}!{item.refs[0].row}–{item.refs[-1].row}",
                      "Проверка": test}
        for key, control in self.properties.items():
            value = values.get(key)
            control.setText(str(value) if value not in (None, "") else "—")

    def set_audit(self, report):
        self.audit_fails = {key for f in report.findings if f.status == "FAIL" for key in f.ids if key in self.by_id}
        self.audit_unknown = {key for f in report.findings if f.status == "UNVERIFIED" for key in f.ids
                              if key in self.by_id}
        self.load_rows()
        self.apply_filters()

    def center_selected(self):
        if self.current and self.current in self.by_id:
            if self.current not in self.scene.shapes:
                self.reveal(self.current)
            self.set_selection(self.current, center=True)

    def default_view(self):
        self.scene.view_isometric()
        self.scene.fit_all()

    def toggle_projection(self, checked):
        if checked:
            self.scene.enable_parallel_projection()
        else:
            self.scene.disable_parallel_projection()
        self.parallel.setText("Ортографическая" if checked else "Перспектива")
        self.scene.render()

    def toggle_grid(self, value):
        self.scene.grid = value
        self.scene.rebuild_grid()
        self.scene.render()

    def set_full(self, enabled):
        self.full = enabled
        self.tree_panel.setVisible(not enabled)
        self.right_panel.setVisible(not enabled)
        self.table_panel.setVisible(not enabled)
        self.full_button.setText("Выйти из полного экрана" if enabled else "На весь экран")

