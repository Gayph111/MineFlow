"""Validate the actual working workbook without calling the splitting/export algorithm."""

from collections import Counter, defaultdict
from dataclasses import replace
from itertools import chain, pairwise
from math import isclose, sqrt
from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook
from shapely.geometry import LineString

from services.audit_geometry import audit_groups, text, traces_match, valid_coords
from services.audit_numbering import audited_numbering
from services.result_audit import (AuditReport, _check_numeric, _compare_sources, _example_match,
                                   _polygon, _records, _reference)
from services.task import Task
from services.workbook_schema import CATEGORY, HEADINGS, WORK_KIND, manifest

EPS = 1e-8
TO_CATEGORY = {title: code for code, title in CATEGORY.items()}


def _matches(a, b):
    return a is not None and b is not None and all(
        x is y if x is None or y is None else abs(x - y) <= EPS for x, y in zip(a, b)
    )


def _length(path, dim):
    if len(path) < 2 or any(p[2] is None for p in path) and dim == 3:
        return None
    return sum(sqrt(sum((a[i] - b[i]) ** 2 for i in range(dim))) for a, b in zip(path, path[1:]))


def _reconcile_path(original, paths):
    """Walk original straight edges. Permits only forward cuts on each edge."""
    if not paths or not original or not _matches(original[0], paths[0][0]):
        return False
    points = list(paths[0])
    for part in paths[1:]:
        if not _matches(points[-1], part[0]):
            return False
        points.extend(part[1:])
    stage = 0
    last_fraction = 0.0
    for q in points[1:]:
        if stage + 1 >= len(original):
            return False
        start, end = original[stage:stage + 2]
        if _matches(q, end):
            stage += 1
            last_fraction = 0.0
            continue
        axes = tuple(i for i in (0, 1, 2) if start[i] is not None and end[i] is not None and q[i] is not None)
        axis = max(axes, key=lambda i: abs(end[i] - start[i]), default=0)
        span = end[axis] - start[axis]
        if not span:
            return False
        fraction = (q[axis] - start[axis]) / span
        if not last_fraction <= fraction < 1:
            return False
        estimated = tuple(start[i] + (end[i] - start[i]) * fraction if i in axes else None for i in range(3))
        if not _matches(q, estimated):
            return False
        last_fraction = fraction
    return stage == len(original) - 1


def _reference_polygons(source, config):
    if config.contour is None:
        return {}
    contours = audit_groups(source.sheet(config.contour.sheet), config.contour, config)
    by_level = defaultdict(list)
    for shape in contours.values():
        by_level[shape.level].append((shape, _polygon(shape)))
    return by_level


def _outline_candidates(group, contours, single_body):
    candidates = [(shape, polygon) for shape, polygon in contours.get(group.level, ())
                  if shape.body == group.body or (not shape.body and single_body)]
    empty_invalid = any(not shape.body and polygon is None for shape, polygon in contours.get(group.level, ()))
    return candidates, empty_invalid


def _is_copy(group, candidates):
    return any(poly is not None and traces_match(group.coords, outline.coords) for outline, poly in candidates)


def _ordered_points(points, segments, report):
    buckets = defaultdict(list)
    for row in points:
        key = row.get("ID участка")
        if key not in segments:
            report.add("orphan_vertex", "FAIL", "Точка без участка", key, "ID существующего участка")
            continue
        f, i = row.get("Фрагмент"), row.get("Порядок точки")
        xyz = tuple(row.get(axis) for axis in ("EAST", "NORTH", "RL"))
        dimensions = (xyz[:2] if xyz[2] is None else xyz)
        if (type(f) is not int or type(i) is not int or f < 1 or i < 1
                or any(type(x) not in (float, int) or not -1e15 <= x <= 1e15 for x in dimensions)):
            report.add("invalid_vertex", "FAIL", key, xyz, "Числа EAST / NORTH / RL и положительный порядок", (key,))
            continue
        buckets[key].append((f, i, xyz, row.get("Происхождение"), row.get("Строки Excel")))
    result = {}
    for key, rows in buckets.items():
        sections = defaultdict(list)
        ordered = sorted(rows, key=lambda v: v[:2])
        for f, i, point, _, _ in ordered:
            if i != len(sections[f]) + 1:
                report.add("vertex_order", "FAIL", key, f"{f} / {i}", "Последовательный порядок без дубликатов", (key,))
            sections[f].append(point)
        if list(sections) != list(range(1, len(sections) + 1)):
            report.add("fragment_order", "FAIL", key, list(sections), "Непрерывный порядок фрагментов", (key,))
        result[key] = tuple(tuple(section) for section in sections.values())
    return result, buckets


def _category_check(path, cat, poly, config, axis):
    if axis.polyline is None or axis.closed:
        return cat is None
    if config.split_rule == "whole" and config.classification == "source":
        return cat == axis.source_category
    if not poly or len(path) < 2:
        return cat is None
    shape = LineString([p[:2] for p in path])
    if shape.length <= EPS:
        loc = shape.centroid
        expected = "R" if poly.contains(loc) else "P" if poly.disjoint(loc) else None
        return cat == (expected if config.split_rule == "contour" else None)
    if config.split_rule == "whole":
        expected = "P" if shape.disjoint(poly) else "R" if poly.contains(shape) and shape.disjoint(poly.boundary) else None
        if axis.source_category and expected != axis.source_category:
            expected = None
        return cat == expected
    inner = shape.intersection(poly.buffer(-EPS)).length
    outer = shape.difference(poly.buffer(EPS)).length
    if cat == "P":
        return inner <= EPS and outer > EPS
    if cat == "R":
        return outer <= EPS and inner > EPS
    return inner <= EPS and outer <= EPS


def _expected_links(config, groups, pieces, order, paths):
    candidates = []
    if config.link_rule == "continuity":
        for keys in order.values():
            for a, b in pairwise(keys):
                first, second = paths.get(a, ()), paths.get(b, ())
                if first and second and _matches(first[-1][-1], second[0][0]):
                    candidates.append((a, b))
    elif config.link_rule == "explicit":
        scopes = defaultdict(list)
        for parent, keys in order.items():
            g = groups[parent]
            if g.pair and len(keys) == 1:
                scopes[g.level, g.body, g.pair].extend(keys)
        candidates.extend(tuple(keys) for keys in scopes.values() if len(keys) == 2)

    viable = [(a,b) for a,b in candidates if {pieces[a][1], pieces[b][1]} == {"P", "R"}
              and all(pieces[k][0].polyline and not pieces[k][0].source_conflict and not pieces[k][0].pair_conflict
                      for k in (a,b))]
    degree = Counter(chain.from_iterable(viable))
    review = {k for a,b in viable if degree[a] != 1 or degree[b] != 1 for k in (a,b)}
    ordered = {(a,b) if pieces[a][1] == "P" else (b,a) for a,b in viable if degree[a] == degree[b] == 1}
    return ordered, review



def _check_reference(path, source, config, groups, axes, book_rows, report):
    if path is None:
        report.add("reference", "UNVERIFIED", "Производственный эталон",
                   "Полного эталона нет", "Утверждённая ведомость заказчика")
        return
    reference = None
    try:
        reference = load_workbook(path, read_only=True, data_only=False)
        reference_roles = manifest(reference).get("sheets")
        if reference_roles:
            for role, headings in HEADINGS.items():
                rows = _records(reference, reference_roles[role], headings, report)
                a = Counter(tuple(row.get(c) for c in headings) for row in rows)
                b = Counter(tuple(row.get(c) for c in headings) for row in book_rows[role])
                report.check("reference_compare", f"Сверка с эталоном · {role}",
                             (sum((a - b).values()), sum((b - a).values())), (0, 0))
            return
    except Exception as error:
        report.add("reference", "UNVERIFIED", path.name, str(error), "Читаемая эталонная книга Excel")
        return
    finally:
        if reference:
            reference.close()
    normalized = {k: {"Лист": row.get("Лист Excel"), "Первая строка": row.get("Первая строка"),
                      "Группа Excel": row.get("JOIN"), "Горизонт": row.get("Горизонт"),
                      "Рудное тело": row.get("Рудное тело"), "Длина расчётная": row.get("Длина оси"),
                      "Длина начало–конец": groups[k].chord if k in groups else None,
                      "Категория обработки": None, "Пробный номер": None, "Пробная маркировка": None,
                      "Пробное имя на кириллице": None, "Связанные ID": None,
                      "STRING и TUN_NAME из примера": row.get("STRING / TUN_NAME из образца"),
                      "Имя на кириллице из примера": row.get("Имя из образца")} for k, row in axes.items()}
    # The legacy/reference raw-sheet comparator matches customer columns by source vertex rows.
    _reference(path, groups, normalized, source, config, report)


def audit_delivery(source, config, path: Path, reference: Path | None = None, task: Task | None = None):
    report = AuditReport(source.origin or source.name, path.name)
    task = task or Task()
    task.report(7, "Проверка структуры рабочей книги")
    try:
        with ZipFile(path) as zip_file:
            bad = zip_file.testzip()
        if bad:
            raise ValueError(f"Повреждённая часть XLSX: {bad}")
        book = load_workbook(path, read_only=True, data_only=False)
    except Exception as error:
        report.add("archive", "FAIL", path.name, str(error), "Читаемая книга Excel")
        return report
    try:
        roles = manifest(book).get("sheets")
        originals = [s.title for s in source.sheets]
        if not roles:
            report.add("manifest", "FAIL", path.name, "Не найдены рабочие листы", list(HEADINGS))
            return report
        report.check("sheets", "Исходные и рабочие листы", book.sheetnames,
                     originals + [roles[k] for k in HEADINGS])
        _compare_sources(source, book, report, task)
        rows = {role: _records(book, roles[role], headings, report) for role, headings in HEADINGS.items()}
        groups = audit_groups(source.sheet(config.working.sheet), config.working, config)
        report.objects = len(groups)
        report.rows = sum(len(g.refs) for g in groups.values())
        report.outline_rows = (len(source.sheet(config.contour.sheet).rows) - config.contour.header) if config.contour else 0
        report.segments = len(rows["segments"])
        report.links = len(rows["links"])
        contours = _reference_polygons(source, config)
        body_scope = defaultdict(set)
        for g in groups.values():
            body_scope[g.level].add(g.body)
        axis_rows = {row.get("ID оси"): row for row in rows["axes"]}
        work_rows = {row.get("ID участка"): row for row in rows["segments"]}
        report.check("axis_ids", "Уникальность и состав осей",
                     Counter(r.get("ID оси") for r in rows["axes"]), Counter(groups.keys()))
        report.check("segment_ids", "Дубли ID участков", len(rows["segments"]) - len(work_rows), 0)
        paths, point_rows = _ordered_points(rows["points"], work_rows, report)
        order = defaultdict(list)
        for key, row in work_rows.items():
            parent, ordinal = row.get("ID оси"), row.get("Порядок")
            if parent not in groups or type(ordinal) is not int or key != f"{parent}.{ordinal}" or ordinal < 1:
                report.add("segment_parent", "FAIL", key, (parent, ordinal), "Существующая исходная ось и номер участка", (key,))
                continue
            order[parent].append((ordinal, key))
        order = {parent: [key for _, key in sorted(keys)] for parent, keys in order.items()}

        task.report(41, "Независимая сверка исходных осей, участков и длин")
        dim = 3 if config.length_mode == "XYZ" else 2
        pieces = {}
        for parent, g in groups.items():
            task.check()
            title = f"{parent} · JOIN {g.key} · RL {g.level} · строки {g.refs[0]}–{g.refs[-1]}"
            candidates, empty_invalid = _outline_candidates(g, contours, len(body_scope[g.level]) == 1 and len(config.bodies) <= 1)
            duplicate = _is_copy(g, candidates)
            polygon = candidates[0][1] if len(candidates) == 1 and not empty_invalid else None
            actual = axis_rows.get(parent, {})
            evidence = _example_match(g)
            expected_axis = {"JOIN": g.key, "Горизонт": g.level or None, "Рудное тело": g.body or None,
                             "Лист Excel": config.working.sheet, "Первая строка": g.refs[0], "Последняя строка": g.refs[-1],
                             "Исходных точек": len(g.refs), "Роль": "Копия контура" if duplicate else "Ось",
                             "STRING / TUN_NAME из образца": evidence.mark if evidence else None,
                             "Имя из образца": evidence.name if evidence else None,
                             "ВИД_РАБОТ из образца": evidence.work_kind if evidence else None,
                             "Источник образца": evidence.citation if evidence else None}
            for column, value in expected_axis.items():
                if actual.get(column) != value:
                    report.check("axis_value", f"{title} · {column}", actual.get(column), value, (parent,))
            length = actual.get("Длина оси")
            report.add("axis_length", "PASS" if _check_numeric(length, g.polyline) else "FAIL",
                       f"{title} · длина оси", length, g.polyline, (parent,))
            if evidence:
                report.check("example", f"{title} · обозначение по сопроводиловке",
                             actual.get("STRING / TUN_NAME из образца"), evidence.mark, (parent,))
            if g.polyline is not None and type(length) in (int, float):
                report.lengths += 1
                report.max_length_delta = max(report.max_length_delta, abs(length - g.polyline))
            keys = order.get(parent, [])
            allowed = bool(keys) != duplicate and (config.split_rule == "contour" or len(keys) <= 1)
            if not allowed or keys != [f"{parent}.{i}" for i in range(1, len(keys) + 1)]:
                report.add("axis_parts", "FAIL", title, keys, "Последовательные участки исходной оси или исключённая копия", (parent,))
            if duplicate:
                continue
            expected_xy = g.coords
            flattened = [part for key in keys for part in paths.get(key, ())]
            if g.polyline is not None:
                geometry_ok = _reconcile_path(expected_xy, flattened)
            else:
                geometry_ok = Counter(p for part in flattened for p in part) == Counter(expected_xy)
                report.add("incomplete_axis", "UNVERIFIED", title, g.unresolved,
                           "Полные координаты и подтверждённый порядок", (parent, *keys))
            report.check("vertex_conservation", f"{title} · сохранность координат и порядка", geometry_ok, True, (parent, *keys))
            provenance = defaultdict(list)
            data = source.sheet(config.working.sheet)
            for ref in g.refs:
                xyz = valid_coords(data.values(ref), config.working)
                if xyz:
                    provenance[xyz].append(ref)
            total = 0.0
            for key in keys:
                row = work_rows[key]
                spans = paths.get(key, ())
                track = spans[0] if len(spans) == 1 else ()
                first = next(iter(spans[0]), None) if spans else None
                last = spans[-1][-1] if spans else None
                piece_len = _length(track, dim) if g.polyline is not None else None
                chord = _length((track[0], track[-1]), dim) if piece_len is not None else None
                total += piece_len or 0
                cat = TO_CATEGORY.get(row.get("Категория"))
                cat_ok = _category_check(track, cat, polygon, config, g)
                ends_match = all(_check_numeric(row.get(f"{coord} {label}"), point[i] if point else None)
                                 for label, point in (("начала", first), ("конца", last))
                                 for i, coord in enumerate(("EAST", "NORTH", "RL")))
                numbers_ok = _check_numeric(row.get("Длина"), piece_len) and _check_numeric(row.get("Длина начало–конец"), chord)
                basis = ("Геометрия контура" if config.split_rule == "contour" else
                         "Из Excel" if config.classification == "source" else "По положению") if cat else None
                metadata_ok = (row.get("ВИД_РАБОТ") == WORK_KIND.get(cat) and row.get("Основание категории") == basis
                               and row.get("Статус") == "UNVERIFIED"
                               and row.get("Категория") == CATEGORY.get(cat)
                               and (row.get("JOIN"), row.get("Горизонт"), row.get("Рудное тело")) ==
                               (g.key, g.level or None, g.body or None))
                for _, _, p, origin, refs in point_rows.get(key, ()):
                    expected_refs = provenance.get(p)
                    if (origin, refs) != (("Исходная", ", ".join(map(str, expected_refs))) if expected_refs else ("Пересечение", None)):
                        report.add("source_vertex", "FAIL", key, (origin, refs, p), "Проверяемое происхождение точки", (key,))
                status = "PASS" if cat_ok and numbers_ok and ends_match and metadata_ok else "FAIL"
                report.add("section_geometry", status, f"{key} · JOIN {g.key} · {CATEGORY.get(cat, 'категория не определена')}",
                           f"длина {row.get('Длина')}; категория {row.get('Категория')}; "
                           f"геометрия {'согласована' if ends_match and cat_ok else 'не согласована'}",
                           f"длина {piece_len}; координаты и категория согласованы с правилом проекта", (key,))
                if cat is None:
                    report.add("unknown_category", "UNVERIFIED", f"{key} · JOIN {g.key} · RL {g.level}",
                               "Категория пуста", "Подтвердить геометрию, границу или исходное поле категории", (key,))
                pieces[key] = (replace(g, coords=track, polyline=piece_len, chord=chord), cat)
            if g.polyline is not None:
                report.check("length_sum", f"{title} · сумма длин участков",
                             isclose(total, g.polyline, abs_tol=EPS, rel_tol=1e-12), True, (parent, *keys))

        task.report(72, "Проверка пар и нумерации")
        expected, ambiguous = _expected_links(config, groups, pieces, order, paths)
        actual_links = Counter((r.get("Участок Порода"), r.get("Участок Руда")) for r in rows["links"])
        report.check("links", "Однозначные пары по настройке проекта", actual_links, Counter(expected))
        pair_keys = {}
        for rock, ore in sorted(expected):
            pair_keys[rock] = pair_keys[ore] = f"{rock}/{ore}"
        expected_basis = "Непрерывность исходной оси" if config.link_rule == "continuity" else "Идентификатор пары из Excel"
        for row in rows["links"]:
            rock, ore = row.get("Участок Порода"), row.get("Участок Руда")
            if rock in pieces and ore in pieces:
                g = pieces[rock][0]
                report.check("link_scope", f"{rock} ↔ {ore}",
                             (row.get("Горизонт"), row.get("Рудное тело"), row.get("Основание"), row.get("Статус")),
                             (g.level, g.body or None, expected_basis, "UNVERIFIED"), (rock, ore))
        if config.link_rule == "explicit":
            for key, (group, _) in pieces.items():
                if group.pair and key not in pair_keys:
                    report.add("explicit_link", "UNVERIFIED", key, f"Пара {group.pair} не однозначна",
                               "Сопоставить одного партнёра противоположного типа в том же горизонте и теле", (key,))
        for key in sorted(ambiguous):
            g, _ = pieces[key]
            report.add("ambiguous_link", "UNVERIFIED", f"{key} · JOIN {g.key} · RL {g.level}",
                       "У перехода несколько кандидатов; связь отсутствует",
                       "Подтвердить пару или правило обработки N:1", (key,))

        order_index = {key: index for index, key in enumerate(chain.from_iterable(order.values()), 1)}
        # Numbering is tied deterministically to the source-row order, followed by section order.
        ordered_piece_keys = sorted(pieces, key=lambda k: (pieces[k][0].refs[0], order_index[k]))
        adjusted = {k: replace(pieces[k][0], pair=pair_keys.get(k, "")) for k in ordered_piece_keys}
        categories = {k: pieces[k][1] for k in pieces}
        expected_numbers, _ = audited_numbering(adjusted, categories, set(), config)
        marks = Counter(r.get("Обозначение по настройкам") for r in work_rows.values()
                        if r.get("Обозначение по настройкам"))
        report.check("duplicate_marks", "Повторные обозначения", [k for k, n in marks.items() if n > 1], [])
        for key, row in work_rows.items():
            wanted = expected_numbers.get(key, (None, "", ""))
            actual = (row.get("Номер по настройкам"), text(row.get("Обозначение по настройкам")),
                      text(row.get("Имя по настройкам")))
            if actual != wanted:
                report.check("number_by_rule", f"{key} · предварительная нумерация", actual, wanted, (key,))
        report.add("customer_rules", "UNVERIFIED", "Правила АЛРОСА",
                   "Разделение и связи рассчитаны по выбранным настройкам. Окончательные номера не назначены.",
                   "Утвердить правила, справочник типов и формат ведомости")
        _check_reference(reference, source, config, groups, axis_rows, rows, report)
    finally:
        book.close()
    task.report(100, "Проверка рабочей книги завершена")
    return report


def render_review(report):
    lines = ["# Участки и связи для подтверждения", "", f"Источник — {report.source}", "",
             "| Объект | Требует уточнения | Действие |", "|---|---|---|"]
    for item in report.findings:
        if item.status == "UNVERIFIED":
            cells = [part.replace("|", "&#124;").replace("\n", " ")
                     for part in (item.subject, item.actual, item.expected)]
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"

