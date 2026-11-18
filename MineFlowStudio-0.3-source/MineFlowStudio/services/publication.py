from pathlib import Path
import os
from tempfile import TemporaryDirectory

from services.delivery_audit import audit_delivery, render_review
from services.task import Task
from services.workbook_delivery import save_delivery


def publish(result, path: Path, source: Path | None, reference: Path | None, task: Task | None = None):
    task = task or Task()
    if source and path.resolve() == source.resolve():
        raise ValueError("Укажите другое имя для рабочей книги.")
    if path.suffix.lower() != ".xlsx":
        raise ValueError("Укажите расширение .xlsx.")
    with TemporaryDirectory(dir=path.parent, prefix=".mineflow-publish-") as temporary:
        stage = Path(temporary) / path.name
        save_delivery(result, stage, source, task)
        report = audit_delivery(result.source, result.config, stage, reference, task)
        if report.counts["FAIL"]:
            return report, False
        validation = Path(temporary) / f"{path.stem}_VALIDATION_REPORT.md"
        review = Path(temporary) / f"{path.stem}_UNVERIFIED_CASES.md"
        validation.write_text(report.render(), encoding="utf-8")
        review.write_text(render_review(report), encoding="utf-8")
        task.check()
        os.replace(stage, path)
        os.replace(validation, path.with_name(validation.name))
        os.replace(review, path.with_name(review.name))
        return report, True

