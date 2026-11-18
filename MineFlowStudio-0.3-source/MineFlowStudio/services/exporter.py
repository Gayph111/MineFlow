from dataclasses import asdict
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from domain.models import ProcessingResult
from services.task import Task
from services.workbook_schema import (CONTOUR_HEADERS, EXPORT_TAG, ISSUE_HEADERS, ROW_HEADERS,
                                      SUMMARY_HEADERS)

HEADER_FILL = PatternFill("solid", fgColor="253444")
HEADER_TEXT = Font(bold=True, color="FFFFFF")
STRIPE = PatternFill("solid", fgColor="F2F6FA")


def write_values(ws, row, values, header=False, stripe=False):
    for col, value in enumerate(values, 1):
        if value is None and not stripe:
            continue
        cell = ws.cell(row, col, CellRichText([""]) if value == "" else value)
        if isinstance(value, str):
            cell.data_type = "s"
        if header:
            cell.fill = HEADER_FILL
            cell.font = HEADER_TEXT
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        elif stripe:
            cell.fill = STRIPE


def summary(book, name, headings, rows):
    ws = book.create_sheet(name)
    ws.freeze_panes = "B2"
    for i, heading in enumerate(headings, 1):
        width = 36 if heading in {"Сообщение", "Пробная маркировка", "Пробное имя на кириллице"} else 0
        ws.column_dimensions[get_column_letter(i)].width = min(45, max(15, len(heading) + 4, width))
    write_values(ws, 1, headings, header=True)
    ws.row_dimensions[1].height = 32 if len(headings) > 8 else 22
    numeric_columns = {"Длина расчётная", "Длина начало–конец", "Стартовый EAST", "Стартовый NORTH"}
    for index, row in enumerate(rows, 2):
        write_values(ws, index, row, stripe=index % 2 == 0)
        if headings == SUMMARY_HEADERS:
            for col, heading in enumerate(headings, 1):
                if heading in numeric_columns:
                    ws.cell(index, col).number_format = "0.000000"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headings))}{ws.max_row}"


def original_workbook(result, task):
    source = result.source
    if source.xlsx:
        book = load_workbook(BytesIO(source.xlsx), data_only=False, rich_text=True)
        selected = {sheet.title for sheet in source.sheets}
        for sheet in list(book.worksheets):
            if sheet.title not in selected:
                book.remove(sheet)
                continue
            task.report(20, f"Сохранение типов и формул · {sheet.title}")
            model = source.sheet(sheet.title)
            for row_index, row in enumerate(model.rows, 1):
                task.check()
                for col_index, value in enumerate(row, 1):
                    if value == "":
                        sheet.cell(row_index, col_index).value = CellRichText([""])
        return book

    book = Workbook()
    book.remove(book.active)
    for sheet in source.sheets:
        ws = book.create_sheet(sheet.title)
        for index, row in enumerate(sheet.rows, 1):
            task.check()
            write_values(ws, index, row)
    return book


def export_workbook(result: ProcessingResult, destination: Path, task: Task | None = None,
                    source_path: Path | None = None) -> None:
    task = task or Task()
    if destination.suffix.lower() != ".xlsx":
        raise ValueError("Выходной файл должен иметь расширение .xlsx")
    if source_path and destination.resolve() == source_path.resolve():
        raise ValueError("Выберите новый файл для экспорта")
    task.report(5, "Подготовка XLSX")
    book = original_workbook(result, task)
    generated = []
    used = {sheet.title.casefold() for sheet in result.source.sheets}

    def available(base):
        name, i = base, 2
        while name.casefold() in used:
            name = f"{base} {i}"
            i += 1
        used.add(name.casefold())
        generated.append(name)
        return name

    def rows(items):
        for item in items:
            task.check()
            yield item

    tmp = None
    try:
        task.report(55, "Выгрузка расчёта и диагностики")
        result_title = available("MF · Расчёт")
        summary(book, result_title, SUMMARY_HEADERS,
                rows((e.id, e.group, e.horizon, e.body, e.source_category, e.category, e.spatial,
                      e.length, e.input_length, e.pair, ", ".join(e.related), e.number, e.mark,
                      e.anchor.east if e.anchor else None, e.anchor.north if e.anchor else None,
                      e.refs[0].sheet, e.refs[0].row, len(e.refs), e.contour_copy, e.endpoint_length,
                      e.code, e.name, e.designation_basis,
                      e.reference.mark if e.reference else "", e.reference.name if e.reference else "",
                      e.reference.work_kind if e.reference else "", e.reference.citation if e.reference else "")
                     for e in result.excavations))
        summary(book, available("MF · Строки"), ROW_HEADERS,
                rows((e.id, r.sheet, r.row) for e in result.excavations for r in e.refs))
        summary(book, available("MF · Контуры"), CONTOUR_HEADERS,
                rows((c.group, c.horizon, c.body, c.valid, r.sheet, r.row)
                     for c in result.contours for r in c.refs))
        summary(book, available("MF · Проверки"), ISSUE_HEADERS,
                rows((i.severity, i.code, i.message, r.sheet, r.row)
                     for i in result.issues for r in i.refs))
        settings = book.create_sheet(available("MF · Настройки"))
        settings.column_dimensions["A"].width = 24
        settings.column_dimensions["B"].width = 74
        write_values(settings, 1, (EXPORT_TAG, "synthetic" if result.source.synthetic else "original",
                                result.source.origin or result.source.name,
                                json.dumps(generated, ensure_ascii=False)))
        metadata = [(key, json.dumps(value, ensure_ascii=False)) for key, value in asdict(result.config).items()]
        metadata += [("rules_status", "Правила заказчика требуют подтверждения"),
                     ("delivery", "Расчётная ведомость; исходные столбцы сохранены")]
        for index, values in enumerate(metadata, 2):
            write_values(settings, index, values)
        book[result_title].sheet_properties.tabColor = "4DA8FF"
        book.active = book[result_title]
        task.report(85, "Запись книги")
        with NamedTemporaryFile(dir=destination.parent, suffix=".xlsx", delete=False) as file:
            tmp = Path(file.name)
        book.save(tmp)
        task.check()
        os.replace(tmp, destination)
        if task.progress:
            task.progress(100, "Экспорт завершён")
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        book.close()

