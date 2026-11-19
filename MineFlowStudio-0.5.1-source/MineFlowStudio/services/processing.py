from collections import Counter, defaultdict
from dataclasses import dataclass
from time import perf_counter

from domain.case_reference import from_customer_example
from domain.models import (ColumnMap, Contour, Excavation, Point3D, ProcessingConfig,
                           ProcessingResult, RowRef, Value, WorkbookData)
from services.geometry import (GeometryClassification, SourceClassification, contour_signature, path_length,
                               polygon_for, spatial_relation)
from services.importer import cell, present
from services.numbering import assign_axis_numbers, link_pairs
from services.segmentation import build_segments
from services.task import Task
from services.validation import IssueLog, as_text, category, numeric, horizon_key


@dataclass(frozen=True)
class Record:
    ref: RowRef
    point: Point3D | None
    order: float | None
    category: Value
    pair: str
    length: Value
    code: str


def process(source: WorkbookData, config: ProcessingConfig, task: Task | None = None) -> ProcessingResult:
    task = task or Task()
    started = perf_counter()
    log = IssueLog()
    if config.contour and config.working.sheet == config.contour.sheet:
        raise ValueError("Выберите разные листы для выработок и контуров")
    names = [body.name for body in config.bodies]
    marks = [body.mark for body in config.bodies]
    if len(set(names)) != len(names) or len(set(marks)) != len(marks):
        raise ValueError("Названия тел и их маркировки должны быть уникальны")
    if config.first < 1 or not 1 <= config.naming.digits <= 8:
        raise ValueError("Проверьте начальный номер и разрядность")

    task.report(5, "Сопоставление координат выработок")
    groups = collect(source, config.working, log, task)
    if not groups:
        raise ValueError("После строки заголовков нет данных выработок")
    task.report(30, "Проверка контуров")
    outlines = collect(source, config.contour, log, task) if config.contour else {}
    contours = []
    polygons = defaultdict(list)
    contour_paths = set()
    levels_with_invalid_contours = set()

    for (horizon, body, group), records in outlines.items():
        task.check()
        refs, parts = split_points(records, log, config.contour.order is not None, contour=True)
        # Единственное настроенное тело можно связать с листом, где тело не подписано.
        resolved_body = body or (names[0] if len(names) == 1 else "")
        polygon, error = polygon_for(parts)
        complete = all(r.point is not None for r in records)
        if not horizon or not complete or error:
            log.add("Ошибка", "contour", error or "Не указан горизонт или пропущена точка", refs)
            polygon = None
            levels_with_invalid_contours.add((horizon, resolved_body))
        if polygon is not None:
            polygons[horizon].append((resolved_body, polygon))
        contours.append(Contour(group, horizon, resolved_body, refs, parts, polygon is not None))
        if polygon is not None and (signature := contour_signature(parts[0])) is not None:
            contour_paths.add((horizon, resolved_body, signature))

    classifier = GeometryClassification() if config.classification == "geometry" else SourceClassification()
    bodies_by_level = defaultdict(set)
    for horizon, body, _group in groups:
        bodies_by_level[horizon].add(body)
    task.report(55, "Расчёт длин и пространственных отношений")
    objects = []
    polygon_by_axis = {}
    for index, ((horizon, body, group), records) in enumerate(groups.items()):
        task.check()
        if index and index % 250 == 0:
            task.report(55 + 30 * index // len(groups), "Расчёт длин и пространственных отношений")
        refs, parts = split_points(records, log, config.working.order is not None)
        resolved_body = body or (names[0] if len(names) == 1 else "")
        if names and resolved_body not in names:
            log.add("Внимание", "body", "Рудное тело отсутствует в настройках", refs)
        categories = {category(r.category) for r in records if present(r.category)}
        source_category = next(iter(categories)) if len(categories) == 1 else None
        if len(categories) > 1 or None in categories:
            log.add("Ошибка", "source_category", "Нераспознанные или разные категории одной группы",
                    tuple(r.ref for r in records if present(r.category)))
        pair_ids = {r.pair for r in records if r.pair}
        lengths = {r.length for r in records if present(r.length)}
        codes = {r.code for r in records if r.code}
        if len(codes) > 1:
            log.add("Внимание", "code", "У точек одной линии разные значения CODE", refs)
        if len(pair_ids) > 1:
            log.add("Ошибка", "pair_ids", "В группе задано больше одного идентификатора пары", refs)
        if len(lengths) > 1:
            log.add("Внимание", "source_length", "В группе несколько исходных значений ДЛИНА", refs)
        missing = any(r.point is None for r in records)
        length = path_length(parts[0], config.length_mode) if len(parts) == 1 and not missing else None
        if length is None:
            log.add("Ошибка", "length", "Длина недоступна. Проверьте полноту координат и порядок точек", refs)
        elif length == 0:
            log.add("Внимание", "zero_length", "Нулевая длина", refs)
        endpoints = path_length((parts[0][0], parts[0][-1]), config.length_mode) if length is not None else None
        item = Excavation(f"X{min(r.row for r in refs)}", group, horizon, resolved_body, refs, parts,
                          source_category=source_category,
                          pair=next(iter(pair_ids)) if len(pair_ids) == 1 else "",
                          length=length, endpoint_length=endpoints, code=next(iter(codes)) if len(codes) == 1 else "",
                          numbering_blocked=len(pair_ids) > 1 or len(categories) > 1 or None in categories,
                          input_length=next(iter(lengths)) if len(lengths) == 1 else None)
        signature = contour_signature(parts[0]) if len(parts) == 1 and not missing else None
        item.contour_copy = signature is not None and any(
            (horizon, candidate, signature) in contour_paths
            for candidate in (resolved_body, "") if candidate or len(bodies_by_level[horizon]) == 1
        )
        item.reference = from_customer_example(item)
        objects.append(item)
        if item.contour_copy:
            log.add("Внимание", "contour_copy", "Замкнутая ось совпадает с контуром по XYZ с учётом начальной вершины и направления", refs)
            continue
        if item.closed:
            log.add("Внимание", "closed_working", "Замкнутая линия на листе выработок требует проверки", refs)
            continue
        matches = [polygon for contour_body, polygon in polygons[horizon]
                   if contour_body == resolved_body or (not contour_body and len(names) <= 1
                       and len(bodies_by_level[horizon]) == 1)]
        invalid_match = ((horizon, resolved_body) in levels_with_invalid_contours
                         or (horizon, "") in levels_with_invalid_contours)
        if len(matches) == 1 and not invalid_match and not missing:
            polygon_by_axis[item.id] = matches[0]
            item.spatial = spatial_relation(item, matches[0])
            if config.split_rule=="whole" and ("границ" in item.spatial or "касанием" in item.spatial):
                log.add("Внимание", "boundary", f"{item.spatial}. Решение по категории требует проверки", refs)
        elif config.classification == "geometry":
            log.add("Внимание", "contour_match", "Нет однозначного валидного контура для тела и горизонта", refs)
        item.category = classifier.assign(item, log)
        if not item.category and config.split_rule=="whole":
            log.add("Внимание", "category", "Категория Порода или Руда не определена", refs)

    task.report(92, "Проверка пар и пробная нумерация")
    link_pairs(objects, log)
    task.report(95, "Разделение осей и проверка связей участков")
    segments, links = build_segments(objects, polygon_by_axis, config, log, task)
    assign_axis_numbers(objects, segments, config, log)
    task.report(100, "Обработка завершена")
    return ProcessingResult(source, config, tuple(objects), tuple(contours), tuple(log.items),
                            perf_counter() - started, segments, links)


def collect(source: WorkbookData, mapping: ColumnMap, log: IssueLog, task: Task):
    if mapping.east is None or mapping.north is None or mapping.east == mapping.north:
        raise ValueError(f"Лист «{mapping.sheet}». Выберите разные столбцы EAST и NORTH")
    if mapping.group is None:
        raise ValueError(f"Лист «{mapping.sheet}». Выберите столбец идентификатора группы")
    if mapping.horizon is None and mapping.rl is None:
        raise ValueError(f"Лист «{mapping.sheet}». Сопоставьте горизонт или RL")
    sheet = source.sheet(mapping.sheet)
    if not 1 <= mapping.header < len(sheet.rows):
        raise ValueError(f"Лист «{sheet.title}». Проверьте строку заголовков")

    groups = defaultdict(list)
    for index, row in enumerate(sheet.rows[mapping.header:], mapping.header + 1):
        task.check()
        if not any(present(value) for value in row):
            continue
        ref = RowRef(sheet.title, index)
        group = as_text(cell(row, mapping.group))
        body = as_text(cell(row, mapping.body))
        rl_value = cell(row, mapping.rl)
        declared=cell(row,mapping.horizon)
        from_elevation=mapping.horizon==mapping.rl or not present(declared)
        horizon=horizon_key(rl_value if from_elevation else declared,elevation=from_elevation)
        if not horizon:
            log.add("Ошибка", "horizon", "Пустой горизонт и RL", (ref,))
        if not group:
            log.add("Ошибка", "group", "Нет идентификатора. Строка показана отдельно", (ref,))
        try:
            east = numeric(cell(row, mapping.east))
            north = numeric(cell(row, mapping.north))
            point = Point3D(east, north, None)
        except ValueError:
            point = None
            log.add("Ошибка", "coordinates", "Пропущены или некорректны EAST / NORTH", (ref,))
        if point is not None and present(rl_value):
            try:
                point = Point3D(point.east, point.north, numeric(rl_value))
            except ValueError:
                log.add("Ошибка", "rl", "Некорректное значение RL", (ref,))
        order = None
        if mapping.order is not None:
            try:
                order = numeric(cell(row, mapping.order))
            except ValueError:
                log.add("Ошибка", "order", "Пропущен или некорректен порядковый номер точки", (ref,))
        key = (horizon, body, group or f"Строка {index} (без ключа)")
        groups[key].append(Record(ref, point, order, cell(row, mapping.category),
                                  as_text(cell(row, mapping.pair)), cell(row, mapping.input_length),
                                  as_text(cell(row, mapping.code))))
    return groups


def split_points(records: list[Record], log: IssueLog, ordered: bool, contour: bool = False):
    refs = tuple(record.ref for record in records)
    orders = [r.order for r in records]
    if ordered:
        if None not in orders and len(set(orders)) == len(records):
            records = sorted(records, key=lambda record: record.order)
        else:
            log.add("Ошибка", "order_conflict", "Порядок задан не полностью или повторяется. Связь точек отключена", refs)
            return refs, tuple((r.point,) for r in records if r.point is not None)
    elif any(b.row != a.row + 1 for a, b in zip(refs, refs[1:])):
        log.add("Ошибка", "row_order", "Строки группы несмежны. Сопоставьте столбец с порядком точек", refs)
        return refs, tuple((r.point,) for r in records if r.point is not None)
    parts = []
    part = []
    points = Counter()
    closing = records[-1].point
    start = records[0].point
    for index, r in enumerate(records):
        if r.point is None:
            if part:
                parts.append(tuple(part))
                part = []
            continue
        points[r.point] += 1
        is_closure = contour and len(records) > 3 and index == len(records) - 1 and start == closing
        if points[r.point] > 1 and not is_closure:
            log.add("Внимание", "duplicate_point", "Координаты точки повторяются в группе", (r.ref,))
        part.append(r.point)
    if part:
        parts.append(tuple(part))
    return refs, tuple(parts)

