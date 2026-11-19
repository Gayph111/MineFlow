from pathlib import Path

from PySide6.QtWidgets import QApplication
import pytest

from app.ui.audit_dialog import AuditDialog
from app.ui.style import STYLES
from services.result_audit import AuditReport


@pytest.fixture(scope="module")
def app():
    application=QApplication.instance() or QApplication([])
    application.setStyleSheet(STYLES)
    return application


def test_report_statuses_are_russian_but_internal_codes_are_stable(app):
    report=AuditReport("Source","Result")
    report.add("ok","PASS","Расчёт",1,1)
    report.add("bad","FAIL","Подмена",2,1)
    for axis in range(7):
        for part in range(3):
            report.add("ambiguous_link","UNVERIFIED","Связь","Несколько пар","Одна пара",(f"X{axis}.{part+1}",))
    rendered=report.render()
    assert not any(code in rendered for code in ("PASS","FAIL","UNVERIFIED"))
    assert "Пройдено — 1" in rendered and "Ошибки — 1" in rendered
    assert "Требует подтверждения — 21" in rendered
    assert "неоднозначные связи — 21 (исходных осей: 7)" in report.pending_summary()
    assert report.counts["UNVERIFIED"]==21
    dialog=AuditDialog(None,report)
    assert all(row[0] in {"Пройдено","Ошибка","Требует подтверждения"} for row in dialog.model.rows)
    for code,count in (("PASS",1),("FAIL",1),("UNVERIFIED",21)):
        dialog.status_filter.setCurrentIndex(dialog.status_filter.findData(code))
        assert dialog.proxy.rowCount()==count
    dialog.status_filter.setCurrentIndex(0)
    assert dialog.proxy.rowCount()==23
    dialog.close()

