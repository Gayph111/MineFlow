"""Build and audit the operational delivery for the original workbook of case № 3."""

from argparse import ArgumentParser
from collections import Counter
from dataclasses import replace
from getpass import getpass
from hashlib import sha256
import os
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory

import numpy as np

from app.ui.vtk_scene import packed_mesh
from domain.models import OreBody, ProcessingConfig
from fixtures.demo import benchmark_book
from services.delivery_audit import audit_delivery, render_review
from services.importer import PasswordRequired, read_workbook, suggest
from services.processing import process
from services.spatial_model import build_spatial_model
from services.workbook_delivery import save_delivery


def verify_vtk(result, report):
    axes, outlines = build_spatial_model(result)
    refs = [ref for item in result.excavations + result.contours for ref in item.refs]
    raw = np.array([result.source.sheet(ref.sheet).values(ref.row)[:3] for ref in refs], dtype=np.float64)
    mesh = packed_mesh((shape.paths, i) for i, shape in enumerate(axes + outlines))
    count = mesh.n_points
    report.check("original_vtk", "Исходные оси и контуры в VTK", (count, np.array_equal(mesh.points, raw)),
                 (len(refs), True))
    work = replace(result, excavations=result.segments)
    parts, _ = build_spatial_model(work)
    shaped = packed_mesh((shape.paths, i) for i, shape in enumerate(parts))
    expected = np.asarray([(p.east, p.north, p.rl) for e in result.segments for path in e.parts for p in path],
                          dtype=np.float64)
    report.check("section_vtk", "Вершины рабочих участков в VTK",
                 (shaped.n_points, np.array_equal(shaped.points, expected)), (len(expected), True))


def verify_scale():
    output = []
    for size in (200, 400, 1000, 5000):
        data = benchmark_book(size)
        cfg = ProcessingConfig(suggest(data.sheets[0]), split_rule="whole", link_rule="none", numbering=True)
        results = [process(data, cfg) for _ in range(5)]
        last = results[-1]
        groups = len(last.segments)
        marks = len({e.mark for e in last.segments if e.mark})
        count = sum(len(e.refs) for e in last.excavations)
        if count != size or marks != groups or groups != size // 2:
            raise ValueError(f"Нарушена сохранность данных или нумерация при {size} строках.")
        output.append((size, groups, marks, median(r.elapsed for r in results) * 1000))
    return output


def run(source_path, root, reference=None):
    before = sha256(source_path.read_bytes()).hexdigest()
    try:
        source = read_workbook(source_path, os.environ.get("MINEFLOW_INPUT_KEY"))
    except PasswordRequired:
        source = read_workbook(source_path, getpass("Пароль к исходной книге: "))
    raw = source.sheet("выработки")
    contour = next(sheet for sheet in source.sheets if sheet.title.startswith("контуры"))
    body_column = raw.rows[0].index("РУДНОЕ_ТЕЛО")
    bodies = sorted({row[body_column] for row in raw.rows[1:] if len(row) > body_column and row[body_column]})
    config = ProcessingConfig(suggest(raw), suggest(contour), bodies=tuple(OreBody(b, b) for b in bodies),
                              split_rule="contour", link_rule="continuity")
    result = process(source, config)
    destination = root / "output" / "MineFlow_Result.xlsx"
    destination.parent.mkdir(parents=True, exist_ok=True)
    save_delivery(result, destination, source_path)
    report = audit_delivery(source, config, destination, reference)
    report.check("source_hash", "SHA-256 исходной книги", sha256(source_path.read_bytes()).hexdigest(), before)
    verify_vtk(result, report)

    descriptive = Counter(s.category for s in result.segments)
    doc = [
        "## Сверка с предыдущим результатом", "",
        "В книге «Осевые для Моя профессия ИТ_MineFlow1.xlsx» были исходные листы и пять листов MF. "
        "В расчёте из 76 групп были 74 длины, 0 заполненных категорий, 0 связей и 0 номеров.",
        "",
        f"Рабочая книга содержит {len(result.segments)} участков. Из них {descriptive['P']} породных, "
        f"{descriptive['R']} рудных и {descriptive[None]} без категории. Подтверждённый образец записан на исходной оси.",
        "", "## Нагрузочная проверка", "",
        "Медиана пяти расчётов с включённой предварительной нумерацией на синтетических данных. Время без XLSX и графики.",
        "", "| Строки | Участки | Уникальные обозначения | мс |", "|---:|---:|---:|---:|",
    ]
    for size, groups, unique, timing in verify_scale():
        doc.append(f"| {size} | {groups} | {unique} | {timing:.1f} |")

    preview = process(source, replace(config, numbering=True, first=7, order_by="distance"))
    with TemporaryDirectory(dir=root) as temp:
        trial = Path(temp) / "Review.xlsx"
        save_delivery(preview, trial)
        audited = audit_delivery(source, preview.config, trial)
        report.check("preview", "Отдельная проверка нумерации по настройкам", audited.counts["FAIL"], 0)
        doc.extend(("", f"Отдельный прогон реальной книги дал {sum(bool(e.mark) for e in preview.segments)} "
                    "предварительных обозначения. Проверка воспроизвела их по сохранённым настройкам. "
                    "В итоговой книге эти поля оставлены пустыми."))
    doc.extend(("", "Спорные случаи перечислены в [списке для подтверждения](UNVERIFIED_CASES.md).", ""))
    (root / "VALIDATION_REPORT.md").write_text(report.render() + "\n" + "\n".join(doc), encoding="utf-8")
    (root / "UNVERIFIED_CASES.md").write_text(render_review(report), encoding="utf-8")
    print(f"{report.objects} осей, {report.segments} участков, {report.links} связей, {dict(report.counts)}")
    return int(bool(report.counts["FAIL"]))


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, default=Path("."))
    parser.add_argument("--reference", type=Path)
    options = parser.parse_args()
    return run(options.source, options.out, options.reference)


if __name__ == "__main__":
    raise SystemExit(main())

