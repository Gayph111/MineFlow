from dataclasses import fields
from io import BytesIO
import json
from pathlib import Path

import msoffcrypto
from msoffcrypto.exceptions import InvalidKeyError
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from domain.models import ColumnMap, NamingRule, OreBody, ProcessingConfig, SheetData, Value, WorkbookData
from services.task import Task
from services.workbook_schema import EXPORT_TAGS, manifest

OLE = bytes.fromhex("D0CF11E0A1B11AE1")


class PasswordRequired(Exception):
    pass


class InvalidPassword(Exception):
    pass


ALIASES = {
    "east": ("EAST", "X", "ВОСТОК"),
    "north": ("NORTH", "Y", "СЕВЕР"),
    "rl": ("RL", "Z", "ОТМЕТКА"),
    "group": ("JOIN", "ID", "STRING", "TUN_NAME"),
    "horizon": ("ГОРИЗОНТ", "HORIZON", "RL"),
    "body": ("РУДНОЕ_ТЕЛО", "ORE_BODY", "BODY"),
    "category": ("ВИД_РАБОТ", "CATEGORY", "КАТЕГОРИЯ", "ПРИМЕЧАНИЕ"),
    "order": ("ПОРЯДОК", "POINT_ORDER"),
    "pair": ("PAIR_ID", "ID_ПАРЫ"),
    "input_length": ("ДЛИНА", "LENGTH"),
    "code": ("CODE",),
}


def read_workbook(path: Path, password: str | None = None, task: Task | None = None) -> WorkbookData:
    task = task or Task()
    task.report(2, "Открытие книги")
    with path.open("rb") as file:
        signature = file.read(8)
        file.seek(0)
        if signature == OLE:
            office = msoffcrypto.OfficeFile(file)
            if type(office).__name__ != "OOXMLFile" or not office.is_encrypted():
                raise ValueError("Файл имеет старый формат Excel. Сохраните отдельную копию в формате .xlsx.")
            if password is None:
                raise PasswordRequired
            task.report(12, "Расшифровка книги в памяти")
            data = BytesIO()
            try:
                office.load_key(password=password, verify_password=True)
                office.decrypt(data)
            except InvalidKeyError as exc:
                raise InvalidPassword("Пароль не подошёл") from exc
            return _read(data.getvalue(), path.name, task)
        if signature[:2] != b"PK":
            raise ValueError("Файл не является книгой XLSX. Сохраните копию в формате .xlsx.")
        return _read(file.read(), path.name, task)


def _read(xlsx: bytes, name: str, task: Task) -> WorkbookData:
    book = load_workbook(BytesIO(xlsx), read_only=True, data_only=False)
    sheets = []
    synthetic = False
    delivery = manifest(book)
    origin = delivery.get("source")
    config = None
    generated = set(delivery.get("sheets", {}).values())
    try:
        for i, ws in enumerate(book.worksheets):
            if ws.title in generated:
                continue
            task.report(20 + 75 * i // len(book.worksheets), f"Чтение листа «{ws.title}»")
            # Реальные книги могут содержать ошибочный или отсутствующий dimension.
            ws.reset_dimensions()
            rows = []
            for row in ws.iter_rows(values_only=True):
                task.check()
                rows.append(tuple(row))
            if rows and len(rows[0]) >= 4 and rows[0][0] in EXPORT_TAGS:
                synthetic = rows[0][1] == "synthetic"
                origin = str(rows[0][2] or name)
                try:
                    generated.update(json.loads(rows[0][3]))
                    config = _read_config(rows[1:])
                except (TypeError, ValueError, KeyError):
                    config = None
                continue
            sheets.append(SheetData(ws.title, tuple(rows)))
    finally:
        book.close()
    task.report(100, "Книга прочитана")
    sheets = tuple(sheet for sheet in sheets if sheet.title not in generated)
    if not sheets:
        raise ValueError("В книге нет листов с исходными данными")
    if config and (config.working.sheet not in {sheet.title for sheet in sheets}
                   or config.contour and config.contour.sheet not in {sheet.title for sheet in sheets}):
        config = None
    return WorkbookData(name, sheets, synthetic, origin, config, xlsx)


def _read_config(rows):
    settings = {r[0]: json.loads(r[1]) for r in rows if len(r) >= 2
                and r[0] in {field.name for field in fields(ProcessingConfig)}}
    return config_from_dict(settings)


def config_from_dict(data):
    settings = dict(data)
    settings["working"] = ColumnMap(**settings["working"])
    settings["contour"] = ColumnMap(**settings["contour"]) if settings.get("contour") else None
    settings["naming"] = NamingRule(**settings["naming"])
    settings["bodies"] = tuple(OreBody(**body) for body in settings.get("bodies", ()))
    return ProcessingConfig(**settings)


def header_value(sheet: SheetData, header: int, index: int) -> str:
    letter = get_column_letter(index + 1)
    value = cell(sheet.values(header), index) if 0 < header <= len(sheet.rows) else None
    return f"{letter} · {value}" if present(value) else letter


def present(value: Value) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def cell(row: tuple[Value, ...], index: int | None) -> Value:
    return row[index] if index is not None and index < len(row) else None


def suggest(sheet: SheetData, header: int = 1) -> ColumnMap:
    row = sheet.values(header) if 0 < header <= len(sheet.rows) else ()
    headers = {str(v).strip().upper().replace(" ", "_"): i for i, v in enumerate(row) if present(v)}
    suggested = {}
    for field in fields(ColumnMap):
        aliases = ALIASES.get(field.name, ())
        candidates = [headers[a] for a in aliases if a in headers]
        if candidates:
            selected = next((ix for ix in candidates
                             if any(present(cell(r, ix)) for r in sheet.rows[header:header + 150])),
                            candidates[0])
            suggested[field.name] = selected
    return ColumnMap(sheet.title, header, **suggested)

