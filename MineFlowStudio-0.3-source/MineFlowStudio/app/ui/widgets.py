from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QPushButton, QTableView, QAbstractItemView, QHeaderView

from app.ui.style import ERROR
from services.validation import as_text

DISPLAY = Qt.ItemDataRole.DisplayRole
USER = Qt.ItemDataRole.UserRole


def label(text="", name="", wrap=False):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def button(text, callback=None, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setProperty("primary", True)
    if callback:
        widget.clicked.connect(callback)
    return widget


def combo_value(combo):
    return combo.currentData()


class Rows(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.headers = ()
        self.rows = ()
        self.keys = ()
        self.alerts = set()

    def reset(self, headers=(), rows=(), keys=(), alerts=()):
        self.beginResetModel()
        self.headers = tuple(headers)
        self.rows = tuple(rows)
        self.keys = tuple(keys)
        self.alerts = set(alerts)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index, role=DISPLAY):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        raw = row[index.column()] if index.column() < len(row) else None
        if role == DISPLAY:
            return as_text(raw)
        if role == USER:
            return raw if isinstance(raw, (int, float, str)) else as_text(raw)
        if role == Qt.ItemDataRole.ForegroundRole and index.row() in self.alerts:
            return QColor(ERROR)
        if role == Qt.ItemDataRole.TextAlignmentRole and isinstance(raw, (float, int)):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=DISPLAY):
        if role == DISPLAY and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return super().headerData(section, orientation, role)


class Filter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query = ""
        self.restriction = None
        self.setSortRole(USER)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_query(self, query):
        self.query = query.strip().casefold()
        self.invalidateFilter()

    def set_restriction(self, value):
        self.restriction = value
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        key = model.keys[row] if model.keys else None
        if self.restriction is not None and key not in self.restriction:
            return False
        return self.query in " ".join(as_text(v) for v in model.rows[row]).casefold() if self.query else True

    def lessThan(self, left, right):
        def key(value):
            if isinstance(value, (int, float)):
                return 0, value
            return 1, as_text(value).casefold()

        return key(left.data(USER)) < key(right.data(USER))


def table(parent):
    view = QTableView(parent)
    rows = Rows(view)
    proxy = Filter(view)
    proxy.setSourceModel(rows)
    view.setModel(proxy)
    view.setSortingEnabled(True)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.verticalHeader().hide()
    view.verticalHeader().setDefaultSectionSize(28)
    view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    view.horizontalHeader().setDefaultSectionSize(124)
    view.setShowGrid(False)
    return view, rows, proxy


def selected_key(index, model, proxy):
    row = proxy.mapToSource(index).row()
    return model.keys[row] if 0 <= row < len(model.keys) else None

