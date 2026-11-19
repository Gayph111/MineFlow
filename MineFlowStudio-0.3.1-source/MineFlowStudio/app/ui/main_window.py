from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
                              QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLineEdit, QListWidget, QListWidgetItem,
                              QMainWindow, QMessageBox, QProgressBar, QScrollArea, QSplitter,
                              QStackedWidget, QVBoxLayout, QWidget)

from app.ui.audit_dialog import AuditDialog
from app.ui.background import Job
from app.ui.dialogs import MappingDialog
from app.ui.map_view import MapView
from app.ui.rules import RulePanel
from app.ui.widgets import button, label, selected_key, table
from domain.models import OreBody, ProcessingConfig, RowRef
from services.importer import InvalidPassword, PasswordRequired, header_value, read_workbook, suggest
from services.processing import process
from services.delivery_audit import audit_delivery
from services.project_files import PROJECT_SUFFIX, ProjectFile, read_project, write_project
from services.publication import publish
from services.workbook_delivery import save_delivery
from services.validation import as_text

NAV = ("Обзор", "Данные", "Схема 2D", "Правила", "Проверки", "Экспорт", "Схема 3D")
CATEGORY = {None: "Не определена", "R": "Руда · R", "P": "Порода · P"}


def box(widget, kind=QVBoxLayout, margins=(0, 0, 0, 0), spacing=10):
    layout = kind(widget)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def panel(name="panel"):
    frame = QFrame()
    frame.setObjectName(name)
    return frame


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MineFlow Studio")
        self.resize(1330, 810)
        self.setMinimumSize(1010, 670)
        self.source = self.source_path = self.result = None
        self.working = self.contour = None
        self.job = self.outcome = None
        self.by_id, self.by_ref = {}, {}
        self.problem_ids, self.error_refs = set(), set()
        self.selected = ""
        self.source_filter = None
        self.scene3d = None
        self.last_scene = 2
        self.full_scene = False
        self.syncing_selection = False
        self.report = self.exported = self.reference = None
        self.settings = QSettings("MineFlow Studio", "MineFlow Studio")
        self.project_path = None
        self.last_saved_config = None
        self.create_pending = False
        self.closing = False
        self.display = None
        frame = QWidget()
        main = box(frame, QHBoxLayout, spacing=0)
        self.sidebar = self.build_sidebar()
        main.addWidget(self.sidebar)
        right = QWidget()
        body = box(right, spacing=0)
        self.header_widget = self.build_header()
        body.addWidget(self.header_widget)
        content = QWidget()
        content_layout = box(content, margins=(20, 17, 20, 14))
        self.pages = QStackedWidget()
        self.pages.addWidget(self.build_overview())
        self.pages.addWidget(self.build_data())
        self.rules = RulePanel()
        self.rules.changed.connect(self.update_state)
        self.rules.pick_requested.connect(self.pick_start)
        self.pages.addWidget(self.rules)
        self.pages.addWidget(self.build_checks())
        self.pages.addWidget(self.build_export())
        self.scene_stack = QStackedWidget()
        scene_placeholder = QWidget()
        scene_layout = box(scene_placeholder, margins=(20, 20, 20, 20))
        self.scene_note = label("Откройте книгу для построения пространственной модели.", "muted", True)
        scene_layout.addWidget(label("Пространственная модель", "title"))
        scene_layout.addWidget(self.scene_note)
        scene_layout.addStretch()
        self.scene_stack.addWidget(scene_placeholder)
        self.pages.addWidget(self.scene_stack)
        content_layout.addWidget(self.pages)
        body.addWidget(content, 1)
        body.addWidget(self.build_status())
        main.addWidget(right, 1)
        self.setCentralWidget(frame)
        self.exit_full = QShortcut(QKeySequence("Escape"), self)
        self.exit_full.activated.connect(self.exit_scene_full)
        self.navigate(0)
        self.show_data()
        self.update_state()

    def build_sidebar(self):
        sidebar = panel("sidebar")
        sidebar.setFixedWidth(191)
        left = box(sidebar, margins=(15, 16, 15, 16), spacing=7)
        mark = label("MF", "brandIcon")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(40, 40)
        left.addWidget(mark)
        left.addWidget(label("MineFlow Studio", "brand"))
        left.addSpacing(14)
        self.nav_group = QButtonGroup(self)
        for i in (0, 1, 2, 6, 3, 4, 5):
            option = button(NAV[i])
            option.setCheckable(True)
            option.setProperty("nav", True)
            self.nav_group.addButton(option, i)
            left.addWidget(option)
        self.nav_group.idClicked.connect(self.navigate)
        left.addStretch()
        self.source_type = label("Локальный проект", "muted", True)
        left.addWidget(self.source_type)
        self.save_project_button = button("Сохранить проект", self.save_project)
        self.open_project_button = button("Открыть проект…", self.choose_project)
        left.addWidget(self.save_project_button)
        left.addWidget(self.open_project_button)
        return sidebar

    def build_header(self):
        header = panel("header")
        layout = box(header, QHBoxLayout, (20, 9, 20, 9), 12)
        file_info = QVBoxLayout()
        file_info.setSpacing(3)
        file_info.addWidget(label("ПРОЕКТ", "muted"))
        self.project_name = label("Файл не открыт", "section")
        file_info.addWidget(self.project_name)
        layout.addLayout(file_info, 3)
        self.import_status = label("Ожидает импорта", "badge")
        layout.addWidget(self.import_status)
        self.view_kind = QComboBox()
        self.view_kind.addItem("Участки", "segments")
        self.view_kind.addItem("Исходные оси", "axes")
        self.view_kind.currentIndexChanged.connect(self.apply_view)
        layout.addWidget(self.view_kind)
        layout.addWidget(label("Горизонт 2D", "muted"))
        self.levels = QComboBox()
        self.levels.setMinimumWidth(100)
        self.levels.currentIndexChanged.connect(self.show_map)
        layout.addWidget(self.levels)
        self.open_button = button("Открыть Excel", self.choose_file)
        self.process_button = button("Обработать", self.run_processing, primary=True)
        layout.addWidget(self.open_button)
        layout.addWidget(self.process_button)
        return header

    def build_status(self):
        footer = panel("status")
        layout = box(footer, QHBoxLayout, (20, 5, 20, 5))
        self.status = label("Готово к импорту", "muted")
        self.progress = QProgressBar()
        self.progress.setFixedSize(154, 19)
        self.progress.hide()
        self.cancel_button = button("Отменить", self.cancel_job)
        self.cancel_button.hide()
        layout.addWidget(self.status, 1)
        layout.addWidget(self.progress)
        layout.addWidget(self.cancel_button)
        return footer

    def build_overview(self):
        page = QWidget()
        layout = box(page, spacing=11)
        self.overview_title = label("Обзор проекта", "title")
        self.overview_caption = label("", "muted", True)
        layout.addWidget(self.overview_title)
        layout.addWidget(self.overview_caption)
        self.metrics = QWidget()
        row = box(self.metrics, QHBoxLayout, spacing=12)
        self.metric_labels = []
        for caption in ("Строки Excel", "Исходные оси", "Рабочие участки", "Связи на проверку"):
            card = panel("stat")
            card_layout = box(card, margins=(13, 8, 13, 8), spacing=3)
            metric = label("—", "statValue")
            self.metric_labels.append(metric)
            card_layout.addWidget(metric)
            card_layout.addWidget(label(caption, "muted"))
            row.addWidget(card, 1)
        layout.addWidget(self.metrics)

        self.home_card = self.build_projects()
        layout.addWidget(self.home_card, 1)
        split = QSplitter()
        self.map_split = split
        map_card = panel()
        graph_layout = box(map_card, margins=(1, 1, 1, 1), spacing=0)
        titlebar = panel("chartBar")
        bar = box(titlebar, QHBoxLayout, (12, 6, 8, 6), 8)
        bar.addWidget(label("План XY", "section"))
        bar.addWidget(button("Схема 3D", lambda: self.navigate(6)))
        bar.addStretch()
        self.map = MapView()
        self.map.picked.connect(self.map_select)
        self.map.cursor_at.connect(lambda e, n: self.position.setText(f"E {e:.2f}  /  N {n:.2f}"))
        self.map.start_picked.connect(self.update_start)
        for text, fn in (("−", lambda: self.map.zoom(1 / 1.18)), ("+", lambda: self.map.zoom(1.18)),
                         ("Вписать", self.map.fit)):
            bar.addWidget(button(text, fn))
        graph_layout.addWidget(titlebar)
        plan_controls = QWidget()
        plan_bar = box(plan_controls, QHBoxLayout, (10, 4, 10, 4), 8)
        self.plan_search = QLineEdit()
        self.plan_search.setPlaceholderText("Поиск ID, JOIN или обозначения")
        self.plan_search.textChanged.connect(self.show_map)
        self.plan_body = QComboBox()
        self.plan_body.addItem("Все рудные тела", None)
        self.plan_body.currentIndexChanged.connect(self.show_map)
        plan_bar.addWidget(self.plan_search, 1)
        plan_bar.addWidget(self.plan_body)
        graph_layout.addWidget(plan_controls)
        self.chart_stack = QStackedWidget()
        self.chart_stack.addWidget(self.map)
        empty = QWidget()
        blank = box(empty)
        blank.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading = label("На схеме пока нет данных", "section")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        blank.addWidget(heading)
        blank.addWidget(label("Загрузите книгу для просмотра плана XY.", "muted", True))
        blank.addWidget(button("Открыть Excel", self.choose_file, primary=True),
                        alignment=Qt.AlignmentFlag.AlignHCenter)
        self.chart_stack.addWidget(empty)
        graph_layout.addWidget(self.chart_stack, 1)
        controls = QWidget()
        controls.setProperty("plain", True)
        layers = box(controls, QHBoxLayout, (10, 7, 10, 7), 12)
        for title, key in (("Контуры", "contours"), ("Линии", "objects"),
                           ("Номера", "numbers"), ("Проблемы", "issues")):
            check = QCheckBox(title)
            check.setChecked(True)
            check.toggled.connect(lambda active, field=key: self.map.set_layers(**{field: active}))
            layers.addWidget(check)
        layers.addStretch()
        self.position = label("E —  /  N —", "muted")
        layers.addWidget(self.position)
        graph_layout.addWidget(controls)
        split.addWidget(map_card)
        split.addWidget(self.build_inspector())
        split.setSizes([780, 264])
        split.setStretchFactor(0, 9)
        split.setStretchFactor(1, 1)
        split.setCollapsible(0, False)
        split.setCollapsible(1, False)
        layout.addWidget(split, 1)
        return page

    def build_projects(self):
        card = panel()
        layout = box(card, margins=(24, 22, 24, 22), spacing=14)
        layout.addWidget(label("Проекты", "title"))
        layout.addWidget(label("Откройте Excel или продолжите сохранённый проект.", "muted", True))
        actions = QHBoxLayout()
        self.new_project_button = button("Создать проект…", self.new_project, primary=True)
        actions.addWidget(self.new_project_button)
        actions.addWidget(button("Открыть Excel…", self.choose_file))
        actions.addStretch()
        layout.addLayout(actions)
        layout.addSpacing(10)
        layout.addWidget(label("Последние проекты", "section"))
        self.recents = QListWidget()
        self.recents.setStyleSheet("QListWidget { background:#141E29; border:1px solid #344454; border-radius:8px; }"
                                   "QListWidget::item {padding:8px;}")
        self.recents.itemActivated.connect(self.open_recent)
        layout.addWidget(self.recents, 1)
        self.recent_hint = label("Сохранённые проекты появятся здесь.", "muted", True)
        layout.addWidget(self.recent_hint)
        self.refresh_recent()
        return card

    def build_inspector(self):
        card = panel()
        card.setMinimumWidth(240)
        card.setMaximumWidth(338)
        right = box(card, margins=(13, 13, 13, 13))
        right.addWidget(label("Свойства линии", "section"))
        self.inspector_caption = label("Выберите линию на схеме или в таблице.", "muted", True)
        right.addWidget(self.inspector_caption)
        self.inspector_scroll = QScrollArea()
        self.inspector_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.inspector_scroll.setWidgetResizable(True)
        details = QWidget()
        details.setProperty("plain", True)
        form = QFormLayout(details)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(7)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.properties = {}
        for key, text in (("group", "Группа"), ("horizon", "Горизонт"), ("body", "Тело"),
                          ("point", "Старт E / N / RL"), ("length", "Длина"),
                          ("category", "Категория"), ("spatial", "Положение"),
                          ("number", "Номер"), ("mark", "Маркировка"),
                          ("name", "Название"), ("basis", "Основание"), ("axis", "Исходная ось"), ("review", "Проверка"), ("pair", "Связь"), ("rows", "Источник")):
            item = label("—", wrap=True)
            item.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(label(text, "muted"), item)
            self.properties[key] = item
        self.inspector_scroll.setWidget(details)
        right.addWidget(self.inspector_scroll, 1)
        right.addStretch()
        self.source_button = button("Показать исходные строки", self.show_selection_source)
        right.addWidget(self.source_button)
        self.related_button = button("Перейти к связанной линии", self.show_related)
        right.addWidget(self.related_button)
        legend = QHBoxLayout()
        for text, color in (("● Контур", "warning"), ("● Порода", "accent"), ("● Руда", "warning")):
            legend.addWidget(label(text, color))
        right.addLayout(legend)
        return card

    def base_page(self, title, caption):
        page = QWidget()
        layout = box(page, spacing=12)
        layout.addWidget(label(title, "title"))
        layout.addWidget(label(caption, "muted", True))
        return page, layout

    def build_data(self):
        page, layout = self.base_page("Данные", "Строки книги и группы выработок. Двойной щелчок открывает объект на схеме.")
        bar = QHBoxLayout()
        self.data_sheet = QComboBox()
        self.data_sheet.addItem("Рабочие объекты", None)
        self.data_sheet.currentIndexChanged.connect(self.change_data_sheet)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по данным")
        self.mapping_button = button("Листы и столбцы", self.edit_mapping)
        self.map_button = button("На схему", self.open_data_item)
        bar.addWidget(self.data_sheet, 3)
        bar.addWidget(self.search, 3)
        bar.addWidget(button("Сбросить фильтр", self.clear_data_filter))
        bar.addWidget(self.mapping_button)
        bar.addWidget(self.map_button)
        layout.addLayout(bar)
        self.data_table, self.data_model, self.data_proxy = table(page)
        self.search.textChanged.connect(self.data_proxy.set_query)
        self.data_table.doubleClicked.connect(self.open_data_item)
        self.data_table.selectionModel().currentChanged.connect(self.table_selection_changed)
        layout.addWidget(self.data_table, 1)
        self.data_note = label("", "muted", True)
        layout.addWidget(self.data_note)
        return page

    def build_checks(self):
        page, layout = self.base_page("Проверки", "Диагностика с адресами Excel. Двойной щелчок покажет исходные строки.")
        controls = QHBoxLayout()
        self.severity = QComboBox()
        self.severity.addItems(["Все уровни", "Ошибка", "Внимание", "Требуют подтверждения"])
        self.severity.currentTextChanged.connect(self.filter_issues)
        search = QLineEdit()
        search.setPlaceholderText("Поиск по сообщению или адресу Excel")
        controls.addWidget(self.severity, 1)
        controls.addWidget(search, 3)
        self.reference_button = button("Эталон…", self.choose_reference)
        self.audit_button = button("Проверить результат", self.validate_result, primary=True)
        self.audit_details = button("Отчёт проверки", self.show_audit)
        controls.addWidget(self.reference_button)
        controls.addWidget(self.audit_button)
        controls.addWidget(self.audit_details)
        layout.addLayout(controls)
        self.audit_summary = label("Проверка сверяет расчётную книгу с исходными строками.", "muted", True)
        layout.addWidget(self.audit_summary)
        self.check_table, self.check_model, self.check_proxy = table(page)
        search.textChanged.connect(self.check_proxy.set_query)
        self.check_table.doubleClicked.connect(self.open_issue)
        layout.addWidget(self.check_table, 1)
        return page

    def build_export(self):
        page, layout = self.base_page("Экспорт", "Рабочая книга с осями, участками, координатами и связями. Отчёты сохраняются рядом.")
        card = panel()
        content = box(card, margins=(18, 15, 18, 15))
        content.addWidget(label("Книга результатов", "section"))
        self.export_note = label("", "muted", True)
        content.addWidget(self.export_note)
        self.export_button = button("Сохранить XLSX…", self.save_export, primary=True)
        content.addWidget(self.export_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def navigate(self, index):
        if self.full_scene and index != 6:
            self.exit_scene_full()
        self.nav_group.button(index).setChecked(True)
        self.pages.setCurrentIndex((0, 1, 0, 2, 3, 4, 5)[index])
        self.metrics.setVisible(index != 2 and bool(self.result))
        self.overview_title.setText("Схема горизонтов" if index == 2 else "Обзор проекта")
        if index in (2, 6):
            self.last_scene = index
        if index == 6:
            self.activate_3d()

    def activate_3d(self):
        if not self.result:
            self.scene_stack.setCurrentIndex(0)
            self.scene_note.setText("Откройте книгу для построения пространственной модели.")
            return
        try:
            if self.scene3d is None:
                from app.ui.spatial_page import SpatialPage
                self.scene3d = SpatialPage(self.scene_stack)
                self.scene3d.selected.connect(self.map_select)
                self.scene3d.show_plan.connect(lambda: self.navigate(2))
                self.scene3d.full_requested.connect(self.toggle_scene_full)
                self.scene3d.source_rows.connect(lambda key: self.show_refs(self.by_id[key].refs) if key in self.by_id else None)
                self.scene_stack.addWidget(self.scene3d)
            self.scene_stack.setCurrentWidget(self.scene3d)
            if self.scene3d.result is not self.display:
                self.scene3d.set_result(self.display, self.selected)
                if self.report:
                    self.scene3d.set_audit(self.report)
            else:
                self.scene3d.set_selection(self.selected)
        except Exception as error:
            self.scene_stack.setCurrentIndex(0)
            self.scene_note.setText(f"Модуль 3D не запустился: {error}")

    def toggle_scene_full(self):
        if not self.scene3d or self.scene_stack.currentWidget() is not self.scene3d:
            return
        if self.full_scene:
            self.exit_scene_full()
            return
        self.full_scene = True
        self.restore_maximized = self.isMaximized()
        self.sidebar.hide()
        self.header_widget.hide()
        self.scene3d.set_full(True)
        self.showFullScreen()

    def exit_scene_full(self):
        if not self.full_scene:
            return
        self.full_scene = False
        self.scene3d.set_full(False)
        self.sidebar.show()
        self.header_widget.show()
        if self.restore_maximized:
            self.showMaximized()
        else:
            self.showNormal()


    def workbook_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть книгу Excel", "", "Книги Excel (*.xlsx *.xlsm)")
        return Path(path) if path else None

    def choose_file(self):
        if not self.job and (path := self.workbook_dialog()) and self.confirm_switch():
            self.open_file(path)

    def project_destination(self, source):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить проект",
                                              source.with_name(source.stem + PROJECT_SUFFIX).as_posix(),
                                              "Проекты MineFlow (*.mineflow.json)")
        if not path:
            return None
        return Path(path if path.lower().endswith(PROJECT_SUFFIX) else path + PROJECT_SUFFIX)

    def new_project(self):
        if self.job or not (source := self.workbook_dialog()):
            return
        if (destination := self.project_destination(source)) and self.confirm_switch():
            self.open_file(source, create=destination)

    def choose_project(self):
        if not self.job:
            path, _ = QFileDialog.getOpenFileName(self, "Открыть проект", "", "Проекты MineFlow (*.mineflow.json)")
            if path:
                self.open_project(Path(path))

    def open_project(self, path):
        if self.job:
            return
        try:
            project = read_project(path)
        except (OSError, ValueError) as error:
            self.show_error(error)
            return
        missing = not project.source.is_file()
        if missing:
            self.status.setText("Укажите расположение исходной книги для проекта.")
            filename = self.workbook_dialog()
            if not filename:
                return
            project = replace(project, source=filename)
        if self.confirm_switch():
            self.open_file(project.source, project=project, create=project.path if missing else None)

    def open_recent(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.open_project(Path(path))

    def refresh_recent(self):
        self.recents.clear()
        for raw in self.settings.value("recentProjects", [], type=list):
            path = Path(raw)
            if path.is_file():
                item = QListWidgetItem(path.name.removesuffix(PROJECT_SUFFIX))
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                item.setToolTip(str(path))
                self.recents.addItem(item)
        self.recent_hint.setVisible(self.recents.count() == 0)

    def remember_project(self, path):
        recent = [str(path), *(value for value in self.settings.value("recentProjects", [], type=list)
                               if str(value).casefold() != str(path).casefold())]
        self.settings.setValue("recentProjects", recent[:10])
        self.refresh_recent()

    def save_project(self):
        if not self.source_path or not self.working or self.job:
            return False
        try:
            config = self.rules.config(self.working, self.contour)
            target = self.project_path or self.project_destination(self.source_path)
            if not target:
                return False
            project = ProjectFile(target, self.source_path, config)
            write_project(project)
            self.project_path = target.resolve()
            self.last_saved_config = config
            self.remember_project(self.project_path)
            self.display_project()
            self.status.setText(f"Проект сохранён · {self.project_path.name}")
            return True
        except (OSError, ValueError) as error:
            self.show_error(error)
            return False

    def project_dirty(self):
        if not self.source or not self.working:
            return False
        try:
            return self.rules.config(self.working, self.contour) != self.last_saved_config
        except ValueError:
            return True

    def confirm_switch(self):
        if not self.project_dirty():
            return True
        result = QMessageBox.question(self, "Настройки проекта",
                                      "Сохранить изменённые настройки проекта?",
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                      | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        return result == QMessageBox.StandardButton.Discard or (result == QMessageBox.StandardButton.Save and self.save_project())

    def display_project(self):
        if self.source:
            name = self.project_path.name.removesuffix(PROJECT_SUFFIX) if self.project_path else self.source.name
            self.project_name.setText(name if len(name) <= 36 else name[:33] + "…")
            self.project_name.setToolTip(f"{name}\n{self.source_path or ''}")
            self.source_type.setText("Настройки в проекте" if self.project_path else "Книга Excel")

    def open_file(self, path, password=None, project=None, create=None):
        self.start_job(lambda task: read_workbook(path, password, task),
                       lambda data: self.load_data(data, path, project=project, create=create),
                       lambda error: self.import_error(error, path, project, create))

    def import_error(self, error, path, project=None, create=None):
        if isinstance(error, (PasswordRequired, InvalidPassword)):
            prompt = "Пароль не подошёл. Введите пароль ещё раз." if isinstance(error, InvalidPassword) else "Введите пароль к книге Excel."
            value, accepted = QInputDialog.getText(self, "Защищённая книга", prompt, QLineEdit.EchoMode.Password)
            if accepted:
                self.open_file(path, value, project, create)
        else:
            self.show_error(error)

    def load_data(self, data, path=None, default=None, project=None, create=None):
        if project:
            titles = {sheet.title for sheet in data.sheets}
            requested = [m.sheet for m in (project.config.working, project.config.contour) if m]
            if any(title not in titles for title in requested):
                self.show_error(ValueError("В книге отсутствуют листы из сохранённого проекта. Проверьте выбранный Excel."))
                return
        self.project_path = create or (project.path if project else None)
        self.create_pending = bool(create)
        self.source, self.source_path, self.result = data, path, None
        self.display = None
        self.exported = self.report = self.reference = None
        self.reference_button.setText("Эталон…")
        self.selected = ""
        self.by_id, self.by_ref = {}, {}
        self.error_refs = set()
        self.source_filter = None
        self.display_project()
        self.check_model.reset(("Уровень", "Сообщение", "Исходные строки"))
        self.map.clear_map()
        self.show_inspector()
        self.levels.clear()
        self.data_sheet.blockSignals(True)
        self.data_sheet.clear()
        self.data_sheet.addItem("Рабочие объекты", None)
        for sheet in data.sheets:
            self.data_sheet.addItem(sheet.title, sheet.title)
        self.data_sheet.blockSignals(False)
        self.clear_data_filter()

        working = next((s for s in data.sheets if "выработ" in s.title.lower()), data.sheets[0])
        contour = next((s for s in data.sheets if s != working and "контур" in s.title.lower()), None)
        mapping = suggest(working)
        names = sorted({as_text(row[mapping.body]) for row in working.rows[mapping.header:]
                        if mapping.body is not None and len(row) > mapping.body and as_text(row[mapping.body])})
        config = (project.config if project else None) or default or data.config or ProcessingConfig(mapping, suggest(contour) if contour else None,
                                                           tuple(OreBody(n, n) for n in names))
        self.working, self.contour = config.working, config.contour
        self.rules.load_config(config)
        self.last_saved_config = config
        if project and not create:
            self.remember_project(project.path)
        self.navigate(0)
        self.update_state()
        if any(getattr(self.working, key) is None for key in ("east", "north", "group")):
            self.navigate(1)
            self.edit_mapping()
        else:
            self.run_processing()

    def edit_mapping(self):
        if not self.source or self.job:
            return
        dialog = MappingDialog(self, self.source, self.working, self.contour)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.working, self.contour = dialog.working.value(), dialog.contour.value()
            self.run_processing()

    def run_processing(self):
        if not self.source or self.job:
            return
        try:
            config = self.rules.config(self.working, self.contour)
        except ValueError as error:
            self.show_error(error)
            return
        data = self.source
        self.start_job(lambda task: process(data, config, task), self.accept_result)

    def accept_result(self, result):
        self.result = result
        self.report = self.exported = None
        self.audit_summary.setText("Проверка сверяет расчётную книгу с исходными строками.")
        self.error_refs = {ref for issue in result.issues if issue.severity == "Ошибка" for ref in issue.refs}
        self.plan_body.blockSignals(True)
        current_body = self.plan_body.currentData()
        self.plan_body.clear()
        self.plan_body.addItem("Все рудные тела", None)
        for body in sorted({e.body for e in result.excavations} | {c.body for c in result.contours}):
            self.plan_body.addItem(body or "Тело не назначено", body)
        self.plan_body.setCurrentIndex(max(0, self.plan_body.findData(current_body)))
        self.plan_body.blockSignals(False)
        active = self.levels.currentData()
        levels = {e.horizon for e in result.excavations if e.horizon} | {c.horizon for c in result.contours if c.horizon}
        self.levels.blockSignals(True)
        self.levels.clear()
        for level in sorted(levels, key=level_sort, reverse=True):
            self.levels.addItem(level, level)
        self.levels.addItem("Все", None)
        index = self.levels.findData(active) if active is not None else 0
        self.levels.setCurrentIndex(max(0, index))
        self.levels.blockSignals(False)
        sizes = (sum(len(e.refs) for e in result.excavations), len(result.excavations), len(result.segments), len(result.links))
        for metric, value in zip(self.metric_labels, sizes):
            metric.setText(f"{value:,}".replace(",", " "))
        self.check_model.reset(("Уровень", "Сообщение", "Исходные строки"),
                               ((i.severity, i.message, format_refs(i.refs)) for i in result.issues),
                               range(len(result.issues)),
                               (n for n, i in enumerate(result.issues) if i.severity == "Ошибка"))
        self.check_table.setColumnWidth(1, 470)
        self.check_table.setColumnWidth(2, 280)
        self.filter_issues(self.severity.currentText())
        self.status.setText(f"Обработано {len(result.segments)} участков за {result.elapsed * 1000:.1f} мс")
        self.apply_view()
        self.update_state()
        if self.create_pending:
            self.create_pending = False
            self.save_project()

    def apply_view(self, *_):
        if not self.result:
            return
        axes = self.view_kind.currentData() == "axes"
        before = self.by_id.get(self.selected)
        self.display = self.result if axes else replace(self.result, excavations=self.result.segments)
        self.by_id = {item.id: item for item in self.display.excavations}
        self.by_ref = {}
        for item in self.display.excavations:
            for ref in item.refs:
                self.by_ref.setdefault(ref, item.id)
        self.problem_ids = {item.id for item in self.display.excavations
                            if item.review or item.contour_copy or any(ref in self.error_refs for ref in item.refs)}
        if self.report:
            self.problem_ids.update(k for f in self.report.findings if f.status == "FAIL" for k in f.ids if k in self.by_id)
        if self.selected not in self.by_id:
            self.selected = ((before.axis_id or before.id) if before and axes
                             else next((e.id for e in self.display.excavations if before and e.axis_id == before.id), ""))
        self.show_map()
        self.show_data()
        self.show_inspector()
        if self.pages.currentWidget() is self.scene_stack:
            self.activate_3d()

    def show_map(self, _index=None):
        if not self.result:
            return
        level = self.levels.currentData()
        start = (self.result.config.start_east, self.result.config.start_north) if self.result.config.numbering else None
        self.chart_stack.setCurrentIndex(0)
        if not self.display:
            return
        body = self.plan_body.currentData()
        query = self.plan_search.text().strip().casefold()
        objects = [e for e in self.display.excavations if level in (None, e.horizon) and body in (None, e.body)
                   and (not query or query in " ".join((e.id, e.group, e.display_mark, e.display_name)).casefold())]
        outlines = [c for c in self.result.contours if level in (None, c.horizon) and body in (None, c.body)]
        self.map.populate(objects, outlines, self.problem_ids, start)
        self.highlight_map(self.selected)

    def highlight_map(self, item_id, center=False):
        item = self.by_id.get(item_id)
        self.map.highlight(item_id, center=center, related=item.related if item else ())

    def map_select(self, item_id):
        self.selected = item_id
        self.highlight_map(item_id)
        self.show_inspector()
        self.update_table_selection()
        if self.scene3d and self.scene3d.result is self.display and self.scene3d.current != item_id:
            self.scene3d.set_selection(item_id)

    def table_selection_changed(self, current, previous):
        if self.syncing_selection:
            return
        key = selected_key(current, self.data_model, self.data_proxy)
        if isinstance(key, RowRef):
            key = self.by_ref.get(key)
        if key in self.by_id:
            self.map_select(key)

    def update_table_selection(self):
        keys = self.data_model.keys
        obj = self.by_id.get(self.selected)
        if not obj:
            return
        candidate = self.selected
        if self.data_sheet.currentData():
            candidate = next((ref for ref in obj.refs if ref.sheet == self.data_sheet.currentData()), None)
        if candidate in keys:
            index = self.data_proxy.mapFromSource(self.data_model.index(keys.index(candidate), 0))
            if index.isValid():
                self.syncing_selection = True
                self.data_table.setCurrentIndex(index)
                self.data_table.scrollTo(index)
                self.syncing_selection = False

    def show_inspector(self):
        item = self.by_id.get(self.selected)
        self.inspector_caption.setText(item.id if item else "Выберите линию на схеме или в таблице.")
        self.inspector_scroll.setVisible(bool(item))
        self.source_button.setEnabled(bool(item))
        self.related_button.setVisible(bool(item and item.related))
        if not item:
            return
        point = item.anchor
        props = {"group": item.group, "horizon": item.horizon, "body": item.body,
                 "point": f"{point.east:.3f} / {point.north:.3f} / {as_text(point.rl)}" if point else "",
                 "length": (f"{item.length:.3f} {self.result.config.unit}".strip()
                            if item.length is not None else ""),
                 "category": CATEGORY[item.category], "spatial": item.spatial,
                 "number": item.display_number, "mark": item.display_mark, "name": item.display_name,
                 "basis": "По настройкам" if item.axis_id and item.mark else item.designation_basis,
                 "axis": item.axis_id, "review": item.review or ("UNVERIFIED" if item.axis_id else ""),
                 "rows": format_refs(item.refs),
                 "pair": ", ".join(item.related) or item.pair}
        for key, value in props.items():
            self.properties[key].setText(as_text(value) or "—")

    def move_to(self, item_id):
        obj = self.by_id.get(item_id)
        if not obj:
            return
        self.map_select(item_id)
        self.navigate(self.last_scene)
        if self.last_scene == 6 and self.scene3d and self.scene_stack.currentWidget() is self.scene3d:
            self.scene3d.reveal(item_id)
            self.scene3d.set_selection(item_id, center=True)
            return
        ix = self.levels.findData(obj.horizon)
        if ix >= 0 and self.levels.currentIndex() != ix:
            self.levels.setCurrentIndex(ix)
        visible = self.plan_body.currentData() in (None, obj.body)
        if not visible:
            self.plan_body.setCurrentIndex(0)
        if item_id not in self.map.lines:
            self.plan_search.clear()
        self.highlight_map(item_id, center=True)
        self.show_inspector()

    def show_related(self):
        obj = self.by_id.get(self.selected)
        if obj and obj.related:
            self.move_to(obj.related[0])

    def pick_start(self):
        if not self.result:
            self.status.setText("Сначала откройте книгу.")
            return
        self.navigate(2)
        self.map.pick_start = True
        self.status.setText("Щёлкните нужную точку на плане XY.")

    def update_start(self, east, north):
        self.rules.east.setValue(east)
        self.rules.north.setValue(north)
        self.map.set_start((east, north))
        self.navigate(3)

    def change_data_sheet(self, _index):
        self.source_filter = None
        self.show_data()

    def clear_data_filter(self):
        self.source_filter = None
        self.search.clear()
        self.show_data()

    def show_data(self):
        title = self.data_sheet.currentData()
        if self.source and title:
            sheet = self.source.sheet(title)
            mapping = next((m for m in (self.working, self.contour) if m and m.sheet == title), None)
            header = mapping.header if mapping else 1
            width = max((len(row) for row in sheet.rows), default=0)
            headers = ("Строка Excel", *(header_value(sheet, header, i) for i in range(width)))
            refs = tuple(RowRef(title, i) for i in range(1, len(sheet.rows) + 1) if i != header)
            self.data_model.reset(headers, ((r.row, *sheet.values(r.row)) for r in refs), refs,
                                  (i for i, r in enumerate(refs) if r in self.error_refs))
            self.data_proxy.set_restriction(self.source_filter)
            self.data_note.setText(f"Лист «{title}» · " +
                                   (f"показано строк по выбору: {len(self.source_filter)}" if self.source_filter else
                                    f"строк кроме заголовка: {len(refs)}"))
        elif self.display:
            items = self.display.excavations
            self.data_model.reset(("ID", "Группа", "Горизонт", "Рудное тело", "Точек", "Категория",
                                   "Длина XY / XYZ", "Положение", "Номер", "Маркировка", "Основание", "Исходная ось", "Источник"),
                                  ((e.id, e.group, e.horizon, e.body, len(e.refs), CATEGORY[e.category],
                                    round(e.length, 4) if e.length is not None else None,
                                    e.spatial, e.display_number, e.display_mark,
                                    "UNVERIFIED" if e.axis_id else e.designation_basis, e.axis_id, format_refs(e.refs)) for e in items),
                                  (e.id for e in items), (i for i, e in enumerate(items) if e.id in self.problem_ids))
            self.data_proxy.set_restriction(None)
            self.data_note.setText(f"{len(items)} объектов · длина {self.result.config.length_mode}")
        else:
            self.data_model.reset(("Строки", "Результат"))
            self.data_note.setText("Откройте книгу, чтобы просмотреть данные.")
        if not self.data_table.horizontalHeader().isSortIndicatorShown():
            self.data_table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.update_table_selection()


    def open_data_item(self, index=None):
        if index is None or isinstance(index, bool):
            index = self.data_table.currentIndex()
        key = selected_key(index, self.data_model, self.data_proxy)
        if isinstance(key, RowRef):
            key = self.by_ref.get(key)
        if key:
            self.move_to(key)

    def show_refs(self, refs):
        if not refs:
            return
        title = refs[0].sheet
        self.data_sheet.setCurrentIndex(self.data_sheet.findData(title))
        self.source_filter = {ref for ref in refs if ref.sheet == title}
        self.search.clear()
        self.show_data()
        self.navigate(1)

    def show_selection_source(self):
        if self.selected in self.by_id:
            self.show_refs(self.by_id[self.selected].refs)

    def filter_issues(self, text):
        restriction = None
        if self.result and text != "Все уровни":
            if text == "Требуют подтверждения":
                review_codes = {"ambiguous_link", "segment_review", "pair", "pair_ids", "contour_copy",
                                "source_category", "code", "number_conflict", "naming_input"}
                restriction = {i for i, issue in enumerate(self.result.issues) if issue.code in review_codes}
            else:
                restriction = {i for i, issue in enumerate(self.result.issues) if issue.severity == text}
        self.check_proxy.set_restriction(restriction)

    def open_issue(self, index):
        key = selected_key(index, self.check_model, self.check_proxy)
        if key is not None and self.result:
            self.show_refs(self.result.issues[key].refs)

    def save_export(self):
        if not self.result or self.job or not self.export_button.isEnabled():
            return
        name = Path(self.source.name).stem + "_MineFlow.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт XLSX", name, "Книги Excel (*.xlsx)")
        if not path:
            return
        destination = Path(path)
        if not destination.suffix:
            destination = destination.with_suffix(".xlsx")
        result, source = self.result, self.source_path
        reference = self.reference
        self.start_job(lambda task: publish(result, destination, source, reference, task),
                       lambda outcome: self.export_saved(destination, outcome))

    def export_saved(self, destination, outcome):
        report, saved = outcome
        self.accept_audit(report)
        if saved:
            self.exported = destination
            self.export_note.setText(f"{destination.name} · отчёты сохранены рядом с книгой.")
            self.status.setText(f"Рабочая книга и отчёты сохранены · {destination.name}")
        else:
            self.navigate(4)
            self.status.setText("Выгрузка не записана. Проверьте нарушения в отчёте.")

    def choose_reference(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать эталонную книгу", "", "Книги Excel (*.xlsx)")
        if path:
            self.reference = Path(path)
            self.reference_button.setText("Эталон выбран")
            self.reference_button.setToolTip(path)

    def validate_result(self):
        if self.job or not self.result:
            return
        result, candidate, reference = self.result, self.exported, self.reference

        def check(task):
            if candidate:
                return audit_delivery(result.source, result.config, candidate, reference, task)
            with TemporaryDirectory(prefix="mineflow-audit-") as folder:
                target = Path(folder) / "MineFlow_Result.xlsx"
                save_delivery(result, target, task=task)
                return audit_delivery(result.source, result.config, target, reference, task)

        self.start_job(check, self.accept_audit)

    def accept_audit(self, report):
        self.report = report
        counts = report.counts
        self.audit_summary.setText(f"{report.objects} осей · {report.segments} участков · PASS {counts['PASS']} "
                                   f"· FAIL {counts['FAIL']} · UNVERIFIED {counts['UNVERIFIED']}")
        self.status.setText(f"Проверка завершена · {counts['FAIL']} нарушений · "
                            f"{counts['UNVERIFIED']} пунктов требуют подтверждения")
        self.update_state()
        if self.scene3d and self.scene3d.result is self.display:
            if self.pages.currentWidget() is self.scene_stack:
                self.scene3d.set_audit(report)
            else:
                self.scene3d.result = None
        self.problem_ids.update(key for f in report.findings if f.status == "FAIL" for key in f.ids if key in self.by_id)
        self.show_map()
        self.show_data()

    def show_audit(self):
        if self.report:
            AuditDialog(self, self.report).exec()

    def update_state(self, *_):
        busy = self.job is not None
        self.open_button.setEnabled(not busy)
        self.new_project_button.setEnabled(not busy)
        self.open_project_button.setEnabled(not busy)
        self.save_project_button.setEnabled(bool(self.source_path and self.working and not busy))
        self.recents.setEnabled(not busy)
        self.view_kind.setEnabled(bool(self.result))
        self.process_button.setEnabled(bool(self.source) and not busy)
        self.mapping_button.setEnabled(bool(self.source) and not busy)
        self.map_button.setEnabled(bool(self.result))
        self.rules.setEnabled(not busy)
        self.levels.setEnabled(bool(self.result))
        stale = False
        if self.result:
            try:
                stale = self.rules.config(self.working, self.contour) != self.result.config
            except ValueError:
                stale = True
        self.export_button.setEnabled(bool(self.result and not busy and not stale))
        self.audit_button.setEnabled(bool(self.result and not busy and not stale))
        self.audit_details.setEnabled(bool(self.report and not busy))
        self.reference_button.setEnabled(bool(self.result and not busy))
        status = "Ожидает импорта"
        if self.source:
            status = "Импорт выполнен"
        self.import_status.setText("Настройки изменены" if stale else status)
        visible = bool(self.result)
        self.chart_stack.setCurrentIndex(0 if visible else 1)
        self.home_card.setVisible(not visible)
        self.map_split.setVisible(visible)
        self.metrics.setVisible(visible and self.nav_group.checkedId() != 2)
        self.overview_title.setVisible(visible)
        self.overview_caption.setVisible(visible)
        if not self.result:
            self.source_button.setEnabled(False)
            self.related_button.hide()
            self.inspector_scroll.hide()
            self.overview_caption.setText("Выберите книгу Excel с координатами выработок и контуров.")
            for metric in self.metric_labels:
                metric.setText("—")
        else:
            self.overview_caption.setText("Категории из геометрии и рассчитанные связи требуют подтверждения.")
        if stale:
            self.export_note.setText("Примените изменения кнопкой «Обработать».")
        elif self.result:
            self.export_note.setText(f"{len(self.result.segments)} участков · {len(self.result.links)} предварительных связей. "
                                     "Отчёты о проверке и спорных случаях сохранятся отдельно.")
        else:
            self.export_note.setText("Сначала откройте книгу и обработайте данные.")

    def start_job(self, action, done, failure=None):
        if self.job:
            return
        self.outcome = None
        self.job = Job(action, self)
        self.job.progress.connect(self.job_progress)
        self.job.done.connect(lambda result: self.store_outcome(done, result))
        self.job.failed.connect(lambda error: self.store_outcome(failure or self.show_error, error))
        self.job.cancelled.connect(self.job_cancelled)
        self.job.finished.connect(self.job_finished)
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_button.show()
        self.cancel_button.setEnabled(True)
        self.update_state()
        self.job.start()

    def store_outcome(self, action, result):
        self.outcome = action, result

    def job_progress(self, value, text):
        self.progress.setValue(value)
        self.status.setText(text)

    def job_cancelled(self):
        self.status.setText("Операция отменена")

    def cancel_job(self):
        if self.job:
            self.job.stop()
            self.cancel_button.setEnabled(False)
            self.status.setText("Отмена после текущего этапа…")

    def job_finished(self):
        self.job.deleteLater()
        self.job = None
        self.progress.hide()
        self.cancel_button.hide()
        self.update_state()
        if self.closing:
            self.closing = False
            self.outcome = None
            QTimer.singleShot(0, self.close)
            return
        if self.outcome:
            action, result = self.outcome
            self.outcome = None
            action(result)

    def show_error(self, error):
        self.status.setText("Операция завершилась ошибкой")
        QMessageBox.warning(self, "MineFlow Studio", str(error) or type(error).__name__)

    def closeEvent(self, event):
        if self.job:
            self.closing = True
            self.cancel_job()
            event.ignore()
        elif not self.confirm_switch():
            event.ignore()
        else:
            if self.scene3d:
                self.scene3d.scene.close()
            super().closeEvent(event)


def format_refs(refs):
    if not refs:
        return "—"
    if len(refs) == 1:
        return str(refs[0])
    first, last = refs[0], refs[-1]
    return f"{first.sheet}!{first.row}–{last.row} · строк: {len(refs)}"


def level_sort(level):
    try:
        return 1, float(level)
    except ValueError:
        return 0, level

