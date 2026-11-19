from PySide6.QtWidgets import QComboBox, QDialog, QFileDialog, QHBoxLayout, QMessageBox, QVBoxLayout

from app.ui.widgets import button, label, selected_key, table
from domain.status import AUDIT_TITLES, status_title


class AuditDialog(QDialog):
    def __init__(self, parent, report):
        super().__init__(parent)
        self.report = report
        self.setWindowTitle("Проверка результата MineFlow Studio")
        self.resize(1030, 610)
        frame = QVBoxLayout(self)
        frame.addWidget(label("Проверка результата", "title"))
        counts = report.counts
        frame.addWidget(label(f"{report.output} · {report.objects} записей Excel · {report.lengths} длин · "
                              f"Пройдено {counts['PASS']}  /  Ошибки {counts['FAIL']}  /  Требует подтверждения {counts['UNVERIFIED']}",
                              "muted", True))
        frame.addWidget(label(report.pending_summary(), "muted", True))
        controls = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItem("Все статусы", None)
        for code in ("FAIL", "UNVERIFIED", "PASS"):
            self.status_filter.addItem(status_title(code), code)
        controls.addWidget(self.status_filter)
        controls.addStretch()
        controls.addWidget(button("Сохранить отчёт .md", self.save))
        controls.addWidget(button("Закрыть", self.accept))
        frame.addLayout(controls)
        self.view, self.model, self.proxy = table(self)
        self.model.reset(("Статус", "Проверка", "Получено", "Ожидается"),
                         ((status_title(f.status), f.subject, f.actual, f.expected) for f in report.findings),
                         range(len(report.findings)),
                         (i for i, f in enumerate(report.findings) if f.status == "FAIL"))
        for i, width in enumerate((190, 350, 280, 280)):
            self.view.setColumnWidth(i, width)
        self.view.selectionModel().currentChanged.connect(self.details)
        frame.addWidget(self.view, 1)
        self.details_text = label("Выберите строку отчёта для подробностей.", "muted", True)
        frame.addWidget(self.details_text)
        self.status_filter.currentIndexChanged.connect(self.filter_status)
        if counts["FAIL"]:
            self.status_filter.setCurrentIndex(self.status_filter.findData("FAIL"))
        elif counts["UNVERIFIED"]:
            self.status_filter.setCurrentIndex(self.status_filter.findData("UNVERIFIED"))

    def filter_status(self, _index):
        code = self.status_filter.currentData()
        visible = None if code is None else {i for i, f in enumerate(self.report.findings) if f.status == code}
        self.proxy.set_restriction(visible)

    def details(self, current, previous):
        index = selected_key(current, self.model, self.proxy)
        if index is None:
            return
        f = self.report.findings[index]
        self.details_text.setText(f"{f.subject}\nПолучено — {f.actual}\nОжидается — {f.expected}")

    def save(self):
        from pathlib import Path
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить отчёт", "VALIDATION_REPORT.md", "Markdown (*.md)")
        if path:
            try:
                Path(path).write_text(self.report.render(), encoding="utf-8")
            except OSError as error:
                QMessageBox.warning(self, "Сохранение отчёта", str(error))

