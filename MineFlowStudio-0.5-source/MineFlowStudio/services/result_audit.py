"""Audit an exported file against a source snapshot and explicit configuration."""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, replace
from io import BytesIO
from itertools import zip_longest
import json
from math import isclose
from pathlib import Path
from typing import Literal
from zipfile import ZipFile

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell
from shapely.geometry import LineString, Polygon

from domain.case_reference import SUPPLIED_EXAMPLE
from domain.models import ProcessingConfig, WorkbookData
from domain.status import status_title
from services.audit_geometry import audit_groups, text, traces_match, value_at
from services.audit_numbering import audited_numbering, category_for, format_designation
from services.audit_physical_axes import physical_assignment
from services.task import Task
from services.workbook_schema import CONTOUR_HEADERS, EXPORT_TAG, ISSUE_HEADERS, ROW_HEADERS, SUMMARY_HEADERS

Status = Literal["PASS", "FAIL", "UNVERIFIED"]


@dataclass(frozen=True)
class Finding:
    code: str
    status: Status
    subject: str
    actual: str
    expected: str
    ids: tuple[str, ...] = ()


@dataclass
class AuditReport:
    source: str
    output: str
    findings: list[Finding] = field(default_factory=list)
    objects: int = 0
    rows: int = 0
    outline_rows: int = 0
    lengths: int = 0
    segments: int = 0
    links: int = 0
    max_length_delta: float = 0.0

    @property
    def counts(self):
        return Counter(item.status for item in self.findings)

    def add(self, code, status, subject, actual, expected, ids=()):
        self.findings.append(Finding(code, status, subject, str(actual), str(expected), tuple(ids)))

    def check(self, code, subject, actual, expected, ids=()):
        self.add(code, "PASS" if actual == expected else "FAIL", subject, actual, expected, ids)

    def pending_summary(self):
        pending = [f for f in self.findings if f.status == "UNVERIFIED"]
        if not pending:
            return "Все выполненные пункты проверки дали однозначный результат."
        counts = Counter(f.code for f in pending)
        parts = []
        ambiguous = [f for f in pending if f.code == "ambiguous_link"]
        if ambiguous:
            axes = {key.split(".")[0] for f in ambiguous for key in f.ids}
            parts.append(f"неоднозначные связи — {len(ambiguous)} (исходных осей: {len(axes)})")
        incomplete = [f for f in pending if f.code in ("incomplete_axis", "unknown_category")]
        if incomplete:
            axes = {key.split(".")[0] for f in incomplete for key in f.ids}
            parts.append(f"неполные данные — {len(incomplete)} (исходных осей: {len(axes)})")
        known = {"ambiguous_link", "incomplete_axis", "unknown_category"}
        names = {"customer_rules": "согласование правил", "reference": "сверка с эталоном",
                 "numbering_group": "неоднозначные группы нумерации"}
        for code, count in counts.items():
            if code not in known:
                parts.append(f"{names.get(code, 'прочие проверки')}: {count}")
        return ("Счётчик показывает пункты проверки, а не число ошибочных выработок. "
                + "; ".join(parts) + ".")

    def render(self):
        def cell(s):
            return str(s).replace("|", "&#124;").replace("\n", " ").replace("\r", "")
        counts = self.counts
        lines = ["# Проверка результата MineFlow Studio", "", f"Источник — {self.source}",
                 f"Проверенная книга — {self.output}", "",
                 f"Группы — {self.objects}. Строки выработок — {self.rows}. Строки контуров — {self.outline_rows}.",
                 f"Независимо пересчитанные длины — {self.lengths}. "
                 f"Максимальное абсолютное отклонение — {self.max_length_delta:.3g} ед. координат.",
                 f"Пройдено — {counts['PASS']}. Ошибки — {counts['FAIL']}. Требует подтверждения — {counts['UNVERIFIED']}.",
                 self.pending_summary(), "",
                 "| Исходная запись или проверка | Полученный результат | Ожидаемый результат | Статус |",
                 "|---|---|---|---|"]
        if self.segments:
            lines[5:5] = [f"Рабочие участки — {self.segments}. Связи по настройкам проекта — {self.links}.", ""]
        for f in self.findings:
            lines.append("| " + " | ".join(cell(s) for s in (f.subject, f.actual, f.expected, status_title(f.status))) + " |")
        return "\n".join((*lines, ""))


def _signature(cell):
    if cell is None or cell.value is None:
        return None
    value = cell.value
    if cell.data_type == "f" and not isinstance(value, str):
        value = (type(value).__name__, vars(value))
    return cell.data_type, value


def _read_rows(ws):
    ws.reset_dimensions()
    return ws.iter_rows()


def _compare_sources(source, book, report, task):
    original = load_workbook(BytesIO(source.xlsx), read_only=True, data_only=False) if source.xlsx else None
    try:
        for data in source.sheets:
            if data.title not in book:
                report.add("source_sheet", "FAIL", data.title, "Лист отсутствует", "Исходный лист")
                continue
            count = 0
            changed = []
            if original:
                pairs = zip_longest(_read_rows(original[data.title]), _read_rows(book[data.title]), fillvalue=())
                for r, (old, new) in enumerate(pairs, 1):
                    task.check()
                    for c, (old_cell, new_cell) in enumerate(zip_longest(old, new), 1):
                        old_sig, new_sig = _signature(old_cell), _signature(new_cell)
                        if old_sig != new_sig:
                            count += 1
                            if len(changed) < 20:
                                changed.append((Cell(book[data.title], row=r, column=c).coordinate, old_sig, new_sig))
            else:
                book[data.title].reset_dimensions()
                values = book[data.title].iter_rows(values_only=True)
                for r, (old, new) in enumerate(zip_longest(data.rows, values, fillvalue=()), 1):
                    task.check()
                    for c, (a, b) in enumerate(zip_longest(old, new), 1):
                        if (a, type(a)) != (b, type(b)):
                            count += 1
                            if len(changed) < 20:
                                changed.append((Cell(book[data.title], row=r, column=c).coordinate, a, b))
            report.check("source_cells", f"Лист «{data.title}», изменения значений и типов", count, 0)
            for cell, before, after in changed:
                report.add("source_cell", "FAIL", f"{data.title}!{cell}", repr(after), repr(before))
    finally:
        if original:
            original.close()


def _records(book, name, headers, report):
    if name not in book:
        report.add("layout", "FAIL", name, "Нет листа", "Лист расчёта")
        return []
    rows = book[name].values
    actual = tuple(next(rows, ()))
    report.check("layout", f"Лист «{name}», названия и порядок столбцов", actual, headers)
    return [dict(zip(actual, row)) for row in rows if any(value is not None for value in row)]


def _check_numeric(value, expected):
    if expected is None:
        return value is None
    return type(value) in (int, float) and isclose(value, expected, rel_tol=1e-12, abs_tol=1e-9)


def _polygon(item):
    xy = [(p[0], p[1]) for p in item.coords]
    if (len(xy) != len(item.refs) or not item.level or item.unresolved.startswith(("неоднозначный", "несмежные"))
            or len(xy) < 4 or xy[0] != xy[-1] or len(set(xy)) < 3):
        return None
    shape = Polygon(xy)
    return shape if shape.is_valid and shape.area > 0 else None


def _check_contours(contours, rows, sheet, report):
    wanted = {}
    polygons = {}
    for key, group in contours.items():
        polygon = _polygon(group)
        polygons[key] = polygon
        for row in group.refs:
            wanted[sheet, row] = (group.key, group.level, group.body, polygon is not None)
    actual = Counter((row.get("Лист"), row.get("Строка Excel")) for row in rows)
    report.check("contour_rows", "Происхождение и кратность строк контуров", len(actual & Counter(wanted.keys())),
                 len(wanted))
    for ref in sorted(set(wanted) | set(actual), key=repr):
        if actual.get(ref) != int(ref in wanted):
            report.check("contour_ref", ref, actual.get(ref, 0), int(ref in wanted))
    for row in rows:
        ref = row.get("Лист"), row.get("Строка Excel")
        value = (text(row.get("Группа")), text(row.get("Горизонт")), text(row.get("Рудное тело")),
                 row.get("Полигон валиден"))
        if value != wanted.get(ref):
            report.check("contour_value", ref, value, wanted.get(ref))
    return polygons


def _context(group, contours, polygons, unique_body):
    matching = [key for key, contour in contours.items()
                if group.level == contour.level and (contour.body == group.body
                    or not contour.body and unique_body)]
    duplicate = any(polygons[key] is not None and traces_match(group.coords, contours[key].coords)
                    for key in matching)
    has_ordered_xy = (len(group.coords) == len(group.refs) and not
                      group.unresolved.startswith(("неоднозначный", "несмежные")))
    if duplicate or group.closed or not has_ordered_xy or len(matching) != 1:
        return duplicate, ""
    ring = polygons[matching[0]]
    xy = [p[:2] for p in group.coords]
    if ring is None or len(set(xy)) < 2:
        return duplicate, ""
    line = LineString(xy)
    relation = line.relate(ring)
    if relation[0] == "F" and relation[1] == "F" and relation[3] == "F" and relation[4] == "F":
        spatial = "Снаружи"
    elif relation[0] != "F" and relation[2] != "F":
        spatial = "Пересекает границу"
    elif relation[2] == "F" and relation[5] == "F":
        touches = relation[1] != "F" or relation[4] != "F"
        spatial = "На границе" if relation[0] == "F" else "Внутри с касанием" if touches else "Внутри"
    else:
        spatial = "Касается границы"
    return duplicate, spatial



def _connection_rows(rows, groups, sheet, report):
    expected = Counter((key, sheet, number) for key, g in groups.items() for number in g.refs)
    actual = Counter((r.get("ID объекта"), r.get("Исходный лист"), r.get("Строка Excel")) for r in rows)
    report.check("work_refs", "Карта соответствия строк выработок", f"{sum(actual.values())} строк, "
                 f"{sum((expected - actual).values())} пропусков, {sum((actual - expected).values())} лишних",
                 f"{sum(expected.values())} строк, 0 пропусков, 0 лишних")
    for ref in sorted((expected.keys() | actual.keys()), key=repr):
        if expected[ref] != actual[ref]:
            report.check("work_ref", ref, actual[ref], expected[ref], (ref[0],) if ref[0] else ())


def _example_match(group):
    example = SUPPLIED_EXAMPLE
    if (group.key != example.join or group.level != example.horizon or group.body != example.body
            or group.code != example.code or group.polyline is None):
        return None
    if {p[2] for p in group.coords} != {-350.0}:
        return None
    limits = tuple(tuple(sorted(p[axis] for p in group.coords))[i] for axis in (0, 1) for i in (0, -1))
    return (example if all(abs(actual - expected) <= 5e-7 for actual, expected
                           in zip(limits, (*example.east_range, *example.north_range))) else None)


def _result_groups(groups, contours, polygons, rows, config, report, task):
    by_id = {r.get("ID"): r for r in rows}
    repeated = [key for key, count in Counter(r.get("ID") for r in rows).items() if count > 1]
    report.check("object_keys", "Отсутствующие, лишние и повторные ID групп",
                 (sorted(set(groups) - set(by_id), key=repr), sorted(set(by_id) - set(groups), key=repr), repeated),
                 ([], [], []))
    bodies = defaultdict(set)
    for group in groups.values():
        bodies[group.level].add(group.body)
    categories, copies, contexts = {}, set(), {}
    for key, group in groups.items():
        task.check()
        copied, spatial = _context(group, contours, polygons, len(bodies[group.level]) == 1 and len(config.bodies) <= 1)
        contexts[key] = spatial
        if copied:
            copies.add(key)
        categories[key] = category_for(group, {"Положение": spatial}, copied, config)

    physical_values={}
    physical_roots={}
    if config.numbering_unit=="axis":
        _,_,physical_values,physical_roots,_,_,_=physical_assignment(groups,copies,config)
        _,pairs=audited_numbering(groups,categories,copies,replace(config,numbering_unit="source"))
        names={}
        marks=defaultdict(set)
        for key,values in physical_values.items():
            if len(values)==1:
                mark,name=format_designation(groups[key],categories[key],values[0],config)
                names[key]=values[0],mark,name
                if mark:
                    marks[mark].update(physical_roots[key])
        names={key:(n,"" if len(marks[mark])>1 else mark,"" if len(marks[mark])>1 else name)
               for key,(n,mark,name) in names.items()}
    else:
        axis_links = None
        if config.numbering_unit == "linked" and config.link_rule == "explicit" and config.split_rule == "contour":
            # The technical workbook contains original axes. Independently determine which
            # explicit pairs survive as one section per axis after geometric splitting.
            scopes = defaultdict(list)
            material = {"Снаружи": "P", "Внутри": "R", "Касается границы": "P", "Внутри с касанием": "R"}
            for key, g in groups.items():
                if (g.pair and g.polyline and key not in copies and not g.closed
                        and not g.source_conflict and not g.pair_conflict and contexts[key] in material):
                    scopes[g.level, g.body, g.pair].append(key)
            axis_links = [tuple(keys) for keys in scopes.values() if len(keys) == 2
                          and {material[contexts[k]] for k in keys} == {"P", "R"}]
        names, pairs = audited_numbering(groups, categories, copies, config, axis_links=axis_links)
    marked = Counter(text(r.get("Пробная маркировка")) for r in rows if text(r.get("Пробная маркировка")))
    by_mark=defaultdict(set)
    for row in rows:
        mark=text(row.get("Пробная маркировка"))
        key=row.get("ID")
        if mark:
            units=physical_roots.get(key,{key}) if config.numbering_unit=="axis" else {key}
            by_mark[mark].update(units)
    report.check("mark_duplicates","Повторяющиеся обозначения разных линий",
                 [key for key,units in by_mark.items() if len(units)>1],[])
    report.check("missing_numbers", "Количество пробных обозначений согласно выбранному алгоритму",
                 sum(marked.values()), sum(bool(v[1]) for v in names.values()))
    pair_count = sum(bool(text(r.get("Связанные ID"))) for r in rows)
    report.check("pair_count", "Количество групп с явными двусторонними связями", pair_count, len(pairs))
    for key, group in groups.items():
        task.check()
        actual = by_id.get(key)
        if actual is None:
            report.add("object", "FAIL", f"JOIN {group.key}", "Нет рассчитанной строки", key, (key,))
            continue
        address = f"{config.working.sheet}!{group.refs[0]}–{group.refs[-1]} · JOIN {group.key} · RL {group.level}"
        actual_length = actual.get("Длина расчётная")
        chord = actual.get("Длина начало–конец")
        metrics_match = _check_numeric(actual_length, group.polyline) and _check_numeric(chord, group.chord)
        if group.polyline is not None and type(actual_length) in (int, float):
            report.max_length_delta = max(report.max_length_delta, abs(group.polyline - actual_length))
        if group.chord is not None and type(chord) in (int, float):
            report.max_length_delta = max(report.max_length_delta, abs(group.chord - chord))
        report.lengths += group.polyline is not None
        if metrics_match and group.unresolved:
            status = "UNVERIFIED"
            expected = group.unresolved
        else:
            status = "PASS" if metrics_match else "FAIL"
            expected = _lengths(group.polyline, group.chord)
        report.add("length", status, address, _lengths(actual_length, chord), expected, (key,))

        starter = group.coords[0] if group.coords else (None, None, None)
        example = _example_match(group)
        if example:
            report.check("example_mark", f"{address} · STRING и TUN_NAME из сопроводиловки",
                         actual.get("STRING и TUN_NAME из примера"), example.mark, (key,))
            report.check("example_name", f"{address} · имя из сопроводиловки",
                         actual.get("Имя на кириллице из примера"), example.name, (key,))
            report.check("example_length", f"{address} · точная длина из сопроводиловки",
                         round(actual_length, 6) if type(actual_length) in (int, float) else actual_length,
                         example.calculated_length, (key,))
            report.check("example_rounded_length", f"{address} · ДЛИНА при округлении до 0,1",
                         round(actual_length, 1) if type(actual_length) in (int, float) else actual_length,
                         example.displayed_length, (key,))
            if contexts[key] != "Снаружи":
                report.add("example_material_rule", "UNVERIFIED", f"{address} · переход от контура к категории",
                           f"{contexts[key]}; в сопроводиловке {example.work_kind}, суффикс P",
                           "Подтвердить границу участка, отнесённого к породе, и правила разбиения оси", (key,))
        checks = {
            "Группа Excel": group.key, "Горизонт": group.level, "Рудное тело": group.body,
            "Категория Excel": group.source_category, "Категория обработки": categories[key],
            "ДЛИНА из Excel": group.source_length, "Положение": contexts[key], "ID пары": group.pair,
            "Связанные ID": pairs.get(key, ""), "Лист": config.working.sheet,
            "Первая строка": group.refs[0], "Точек": len(group.refs), "Копия контура": key in copies,
            "CODE Excel": group.code,
            "Пробный номер": names.get(key, (None, "", ""))[0],
            "Пробная маркировка": names.get(key, (None, "", ""))[1],
            "Пробное имя на кириллице": names.get(key, (None, "", ""))[2],
            "Статус обозначения": "По настройкам · предварительно" if key in names else "Несколько линий в записи Excel" if len(physical_values.get(key,()))>1 else "Из примера" if example else "Не присвоено",
            "ВИД_РАБОТ из примера": example.work_kind if example else "",
            "Источник примера": example.citation if example else "",
            **({"STRING и TUN_NAME из примера": "", "Имя на кириллице из примера": ""} if not example else {}),
        }
        for column, expected_value in checks.items():
            value = actual.get(column)
            if value is None and expected_value == "":
                value = ""
            if value != expected_value or (value is not None and type(value) is not type(expected_value)):
                report.add("group_value", "FAIL", f"{address} · {column}", repr(value), repr(expected_value), (key,))
        for column, expected_value in zip(("Стартовый EAST", "Стартовый NORTH"), starter):
            if not _check_numeric(actual.get(column), expected_value):
                report.check("anchor", f"{address} · {column}", actual.get(column), expected_value, (key,))
    return by_id, copies


def _lengths(polyline, chord):
    def shown(value):
        return "—" if value is None else f"{value:.9f}" if type(value) in (float, int) else repr(value)
    return f"по оси {shown(polyline)}, начало–конец {shown(chord)}"


def _reference(reference, groups, results, source, config, report):
    if reference is None:
        report.add("reference", "UNVERIFIED", "Построчное сравнение с эталоном", "Готовая ведомость не приложена",
                   "Заполненный и утверждённый заказчиком XLSX")
        return
    try:
        book = load_workbook(reference, read_only=True, data_only=False)
    except (OSError, ValueError, KeyError) as error:
        report.add("reference", "UNVERIFIED", reference.name, str(error), "Доступный эталонный XLSX")
        return
    try:
        _compare_reference_book(book, groups, results, source, config, report)
    finally:
        book.close()


def _compare_reference_book(book, groups, results, source, config, report):
    for ws in book.worksheets:
        rows = ws.values
        headings = tuple(next(rows, ()))
        if headings == SUMMARY_HEADERS:
            reference = {r[0]: dict(zip(headings, r)) for r in rows if r and r[0]}
            columns = ("Лист", "Первая строка", "Группа Excel", "Горизонт", "Рудное тело")
            for key in sorted(reference.keys() | results.keys()):
                address = f"Эталон · {key}"
                a, b = results.get(key), reference.get(key)
                if not a or not b or tuple(a[c] for c in columns) != tuple(b[c] for c in columns):
                    report.add("reference_group", "FAIL", address, "Разные ключи происхождения",
                               "Одна и та же группа и исходные строки", (key,))
                    continue
                for column in ("Длина расчётная", "Длина начало–конец", "Категория обработки",
                               "Пробный номер", "Пробная маркировка", "Пробное имя на кириллице", "Связанные ID"):
                    same = (_check_numeric(a[column], b[column]) if type(b[column]) in (int, float)
                            else text(a[column]) == text(b[column]))
                    report.add("reference_value", "PASS" if same else "FAIL",
                               f"{address} · {column}", a[column], b[column], (key,))
            return

    sheet = config.working.sheet
    if sheet not in book:
        report.add("reference", "UNVERIFIED", "Сопоставимость эталона", "Отсутствует исходный лист или ведомость",
                   "Те же лист, координаты и адреса строк либо согласованные идентификаторы групп")
        return
    original_rows = source.sheet(sheet).rows
    ws = book[sheet]
    ws.reset_dimensions()
    ref_rows = list(ws.values)
    header_index = config.working.header - 1
    if len(ref_rows) <= header_index:
        report.add("reference", "UNVERIFIED", sheet, "Нет заголовка", "Лист с заголовками исходной книги")
        return
    header = {text(v).upper(): i for i, v in enumerate(ref_rows[header_index]) if text(v)}
    properties = {"TUN_NAME": "Пробная маркировка", "ИМЯ_НА_КИРИЛЛИЦЕ": "Пробное имя на кириллице",
                  "ДЛИНА": "Длина расчётная"}
    compared = 0
    for key, g in groups.items():
        if not all(i <= len(ref_rows) and all(
                value_at(original_rows[i - 1], col) == value_at(ref_rows[i - 1], col)
                for col in (config.working.east, config.working.north, config.working.rl, config.working.group))
                   for i in g.refs):
            report.add("reference_group", "UNVERIFIED", f"Эталон · JOIN {g.key}", "Другие координаты или ключи",
                       "Одинаковые исходные записи", (key,))
            continue
        for source_column, result_column in properties.items():
            if source_column not in header or key not in results:
                continue
            values = {value_at(ref_rows[i - 1], header[source_column]) for i in g.refs
                      if text(value_at(ref_rows[i - 1], header[source_column]))}
            if not values:
                continue
            actual = results[key].get(result_column)
            if not actual and source_column in ("TUN_NAME", "ИМЯ_НА_КИРИЛЛИЦЕ"):
                evidence = "STRING и TUN_NAME из примера" if source_column == "TUN_NAME" else "Имя на кириллице из примера"
                actual = results[key].get(evidence)
            target = next(iter(values)) if len(values) == 1 else None
            if len(values) > 1:
                report.add("reference_ambiguous", "UNVERIFIED", f"Эталон · JOIN {g.key} · {source_column}",
                           actual, "У группы в эталоне несколько значений", (key,))
                continue
            compared += 1
            if source_column == "ДЛИНА" and type(target) in (int, float):
                from decimal import Decimal
                digits = max(0, -Decimal(str(target)).normalize().as_tuple().exponent)
                same = type(actual) in (int, float) and round(actual, digits) == target
            else:
                same = text(actual) == text(target)
            report.add("reference_value", "PASS" if same else "FAIL",
                       f"Эталон · JOIN {g.key} · {source_column}", actual, target, (key,))
    if not compared:
        report.add("reference", "UNVERIFIED", "Полнота эталона", "Нет заполненных сопоставимых полей",
                   "Утверждённые названия и длины привязаны к исходным строкам")



def audit_export(source: WorkbookData, config: ProcessingConfig, output: Path,
                 reference: Path | None = None, task: Task | None = None) -> AuditReport:
    task = task or Task()
    report = AuditReport(source.origin or source.name, output.name)
    task.report(8, "Открытие и проверка XLSX")
    try:
        with ZipFile(output) as archive:
            broken = archive.testzip()
        if broken:
            report.add("archive", "FAIL", output.name, broken, "Исправная целостность ZIP/OOXML")
            return report
        book = load_workbook(output, read_only=True, data_only=False)
    except Exception as exc:
        report.add("archive", "FAIL", output.name, str(exc), "Читаемый XLSX")
        return report
    report.add("archive", "PASS", output.name, "ZIP и рабочая книга читаются", "Совместимый XLSX")
    try:
        task.report(22, "Сравнение исходных листов и типов ячеек")
        originals = [s.title for s in source.sheets]
        names = []
        for sheet in book.worksheets:
            if sheet.title in originals:
                continue
            records = sheet.values
            first = next(records, ())
            if len(first) < 4 or first[0] != EXPORT_TAG:
                continue
            try:
                names = json.loads(first[3])
                if (not isinstance(names, list) or len(names) != 5 or not all(isinstance(n, str) for n in names)
                        or len(set(names)) != 5 or names[-1] != sheet.title or set(names).intersection(originals)):
                    raise ValueError
                settings = {row[0]: json.loads(row[1]) for row in records
                            if len(row) >= 2 and row[0] in asdict(config)}
                report.check("settings", "Параметры расчёта в книге", settings, asdict(config) | {"bodies": [asdict(b) for b in config.bodies]})
                report.check("origin", "Имя исходной книги", first[2], source.origin or source.name)
            except (ValueError, TypeError):
                report.add("manifest", "FAIL", "Сведения о выпуске", first[3], "Читаемый список листов и настройки")
                names = []
            break
        report.check("sheets", "Порядок и состав листов", book.sheetnames, originals + names)
        _compare_sources(source, book, report, task)
        if not names:
            report.add("manifest", "FAIL", "Сведения о выпуске", "Манифест ведомости отсутствует или повреждён",
                       EXPORT_TAG)
            return report

        task.report(51, "Независимое восстановление групп и длин")
        rows = _records(book, names[0], SUMMARY_HEADERS, report)
        links = _records(book, names[1], ROW_HEADERS, report)
        outline_rows = _records(book, names[2], CONTOUR_HEADERS, report)
        issue_rows = _records(book, names[3], ISSUE_HEADERS, report)
        groups = audit_groups(source.sheet(config.working.sheet), config.working, config)
        contours = audit_groups(source.sheet(config.contour.sheet), config.contour, config) if config.contour else {}
        report.objects = len(groups)
        report.rows = sum(len(g.refs) for g in groups.values())
        report.outline_rows = sum(len(c.refs) for c in contours.values())
        _connection_rows(links, groups, config.working.sheet, report)
        polygons = _check_contours(contours, outline_rows, config.contour.sheet if config.contour else "", report)
        valid_refs = {(config.working.sheet, r) for g in groups.values() for r in g.refs}
        if config.contour:
            valid_refs.update((config.contour.sheet, r) for c in contours.values() for r in c.refs)
        report.check("issue_refs", "Диагностика без адреса исходной строки",
                     sum((row.get("Исходный лист"), row.get("Строка Excel")) not in valid_refs for row in issue_rows),
                     0)

        task.report(75, "Проверка обозначений, связей и геометрии")
        results, copied = _result_groups(groups, contours, polygons, rows, config, report, task)
        report.add("copy_report", "PASS" if not any(f.code == "group_value" and "Копия контура" in f.subject
                                                    for f in report.findings) else "FAIL",
                   "Совпадения выработок с контурами с учётом начальной вершины",
                   ", ".join(groups[key].key for key in sorted(copied)) or "Совпадений нет",
                   "Сохранить исходные строки, исключить копии из маркировки", copied)
        rule_rows = sum(bool(g.source_category) for g in groups.values())
        report.add("customer_numbering", "UNVERIFIED", "Производственная нумерация и названия",
                   f"Явная категория задана у {rule_rows} групп. Проверены выбранные технические правила.",
                   "Эталон заказчика и утверждённые порядок, роли сегментов и справочник типов")
        if not any(g.pair for g in groups.values()):
            report.add("customer_pairs", "UNVERIFIED", "Связи Порода — Руда для исходных выработок",
                       "В источнике нет сопоставленных идентификаторов пары",
                       "Сопоставленные пары либо утверждённое правило их определения")
        _reference(reference, groups, results, source, config, report)
        task.report(100, "Проверка результата завершена")
        return report
    finally:
        book.close()

