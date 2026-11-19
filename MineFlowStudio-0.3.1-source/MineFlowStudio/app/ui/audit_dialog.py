from PySide6.QtWidgets import QComboBox, QDialog, QFileDialog, QHBoxLayout, QMessageBox, QVBoxLayout

from app.ui.widgets import button, label, selected_key, table


class AuditDialog(QDialog):
    def __init__(self, parent, report):
        super().__init__(parent)
        self.report = report
        self.setWindowTitle("Проверка результата MineFlow Studio")
        self.resize(1030, 610)
        frame = QVBoxLayout(self)
        frame.addWidget(label("Проверка результата", "title"))
        counts = report.counts
        frame.addWidget(label(f"{report.output} · {report.objects} групп · {report.lengths} длин · "
                              f"PASS {counts['PASS']}  /  FAIL {counts['FAIL']}  /  UNVERIFIED {counts['UNVERIFIED']}",
                              "muted", True))
        controls = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItems(("Все статусы", "FAIL", "UNVERIFIED", "PASS"))
        controls.addWidget(self.status_filter)
        controls.addStretch()
        controls.addWidget(button("Сохранить отчёт .md", self.save))
        controls.addWidget(button("Закрыть", self.accept))
        frame.addLayout(controls)
        self.view, self.model, self.proxy = table(self)
        self.model.reset(("Статус", "Проверка", "Получено", "Ожидается"),
                         ((f.status, f.subject, f.actual, f.expected) for f in report.findings),
                         range(len(report.findings)),
                         (i for i, f in enumerate(report.findings) if f.status == "FAIL"))
        for i, width in enumerate((100, 350, 280, 280)):
            self.view.setColumnWidth(i, width)
        self.view.selectionModel().currentChanged.connect(self.details)
        frame.addWidget(self.view, 1)
        self.details_text = label("Выберите строку отчёта для подробностей.", "muted", True)
        frame.addWidget(self.details_text)
        self.status_filter.currentTextChanged.connect(self.filter_status)
        if counts["FAIL"]:
            self.status_filter.setCurrentText("FAIL")
        elif counts["UNVERIFIED"]:
            self.status_filter.setCurrentText("UNVERIFIED")

    def filter_status(self, text):
        visible = None if text == "Все статусы" else {i for i, f in enumerate(self.report.findings) if f.status == text}
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

