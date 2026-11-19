"""Write working axes, sections, vertices and relationships with intact source sheets."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from openpyxl.packaging.custom import StringProperty

from domain.status import PRELIMINARY
from services.exporter import original_workbook, summary
from services.importer import cell
from services.task import Task
from services.validation import numeric
from services.workbook_schema import CATEGORY, DELIVERY_PROPERTY, HEADINGS, SHEET_ROLES, WORK_KIND

def _coords(point):
    return (point.east, point.north, point.rl) if point is not None else (None, None, None)


def _source_vertices(result):
    by_id = {}
    mapping = result.config.working
    sheet = result.source.sheet(mapping.sheet)
    for axis in result.excavations:
        coords = {}
        for ref in axis.refs:
            values = sheet.values(ref.row)
            try:
                xy = (numeric(cell(values, mapping.east)), numeric(cell(values, mapping.north)))
            except ValueError:
                continue
            try:
                rl = numeric(cell(values, mapping.rl))
            except ValueError:
                rl = None
            coords.setdefault(xy + (rl,), []).append(ref.row)
        by_id[axis.id] = coords
    return by_id


def _rows(result, role):
    if role == "axes":
        for e in result.excavations:
            k = e.reference
            yield (e.id, e.group, e.horizon or None, e.body or None, e.refs[0].sheet, e.refs[0].row, e.refs[-1].row,
                   len(e.refs), e.length, "Копия контура" if e.contour_copy else "Ось",
                   k.mark if k else None, k.name if k else None, k.work_kind if k else None,
                   k.citation if k else None, e.number, ", ".join(map(str,e.numbers)) or None)
    elif role == "segments":
        for e in result.segments:
            end = e.parts[-1][-1] if e.parts and e.parts[-1] else None
            yield (e.id, e.axis_id, e.group, e.ordinal, e.horizon or None, e.body or None, CATEGORY.get(e.category),
                   WORK_KIND.get(e.category), e.length, e.endpoint_length, e.category_basis or None,
                   *_coords(e.anchor), *_coords(end), e.number, e.mark or None, e.name or None, PRELIMINARY,
                   {"line":"Линия","transition":"Переход","unknown":"Не определено","source":"Исходная запись"}[e.line_role],
                   e.number_group or None, ", ".join(map(str,e.numbers)) if e.line_role=="transition" and e.numbers else None)
    elif role == "points":
        known = _source_vertices(result)
        for e in result.segments:
            for fragment, path in enumerate(e.parts, 1):
                for i, point in enumerate(path, 1):
                    values = _coords(point)
                    refs = known[e.axis_id].get(values)
                    yield (e.id, fragment, i, *values, "Исходная" if refs else "Пересечение",
                           ", ".join(map(str, refs)) if refs else None)
    elif role == "links":
        by_id = {e.id: e for e in result.segments}
        for link in result.links:
            parent = by_id[link.rock]
            yield (link.rock, link.ore, parent.horizon or None, parent.body or None, link.basis, PRELIMINARY)


def save_delivery(result, destination: Path, source_path: Path | None = None, task: Task | None = None):
    task = task or Task()
    if destination.suffix.lower() != ".xlsx":
        raise ValueError("Выберите файл с расширением .xlsx.")
    if source_path and destination.resolve() == source_path.resolve():
        raise ValueError("Выберите другое имя. Исходная книга открыта для чтения.")
    task.report(5, "Подготовка исходных листов")
    book = original_workbook(result, task)
    temporary = None
    try:
        titles = {}
        used = {title.casefold() for title in book.sheetnames}
        for i, (role, title) in enumerate(SHEET_ROLES.items()):
            task.report(34 + i * 10, f"Запись листа «{title}»")
            actual, suffix = title, 2
            while actual.casefold() in used:
                actual = f"{title} {suffix}"
                suffix += 1
            titles[role] = actual
            used.add(actual.casefold())
            def rows():
                for row in _rows(result, role):
                    task.check()
                    yield row
            summary(book, actual, HEADINGS[role], rows())
        book.active = book[titles["segments"]]
        book.active.sheet_properties.tabColor = "4DA8FF"
        book.active.sheet_view.zoomScale = 90
        if DELIVERY_PROPERTY in book.custom_doc_props.names:
            del book.custom_doc_props[DELIVERY_PROPERTY]
        book.custom_doc_props.append(StringProperty(name=DELIVERY_PROPERTY, value=json.dumps(
            {"version": 1, "sheets": titles, "source": result.source.origin or result.source.name}, ensure_ascii=False
        )))
        task.report(85, "Сохранение рабочей книги")
        with NamedTemporaryFile(dir=destination.parent, suffix=".xlsx", delete=False) as file:
            temporary = Path(file.name)
        book.save(temporary)
        task.check()
        os.replace(temporary, destination)
        task.report(100, "Рабочая книга сохранена")
    finally:
        book.close()
        if temporary:
            temporary.unlink(missing_ok=True)

