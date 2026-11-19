from collections import defaultdict
from math import cos, hypot, radians, sin
from typing import Protocol

from domain.models import Excavation, ProcessingConfig
from services.validation import IssueLog, as_text, numeric


class NumberingStrategy(Protocol):
    def assign(self, objects: list[Excavation], config: ProcessingConfig, log: IssueLog) -> None: ...


def link_pairs(objects: list[Excavation], log: IssueLog) -> dict[str, tuple[Excavation, ...]]:
    pairs: dict[tuple[str, str, str], list[Excavation]] = defaultdict(list)
    for item in objects:
        if item.pair:
            pairs[item.horizon, item.body, item.pair].append(item)

    valid = {}
    for pair in pairs.values():
        if (len(pair) != 2 or {item.category for item in pair} != {"P", "R"}
                or any(not eligible(item) for item in pair)):
            refs = tuple(ref for item in pair for ref in item.refs)
            log.add("Ошибка", "pair", "Для пары нужны две пригодные линии категорий Порода и Руда", refs)
            continue
        first, second = pair
        first.related, second.related = (second.id,), (first.id,)
        valid[first.id] = valid[second.id] = (first, second)
    return valid


def eligible(item: Excavation) -> bool:
    return bool(item.anchor and item.horizon and item.category and item.length
                and not item.closed and not item.contour_copy and not item.numbering_blocked)


def case_tokens(item: Excavation, config: ProcessingConfig):
    try:
        depth = as_text(abs(numeric(item.horizon)))
    except ValueError:
        return None
    kind = config.naming.kind_code.strip()
    if not item.code or not kind or any("_" in token or not token.isalnum() for token in (item.code, kind)):
        return None
    return depth, item.code, kind


def trial_name(item: Excavation, number: int, body_mark: str, config: ProcessingConfig) -> tuple[str, str]:
    rule = config.naming
    if rule.style == "internal":
        bits = (item.horizon, f"{number:0{rule.digits}}", body_mark, rule.prefix, item.category)
        mark = "_".join(bit for bit in bits if bit)
        return mark, ""
    tokens = case_tokens(item, config)
    assert tokens is not None
    depth, code, kind = tokens
    mark = f"{depth}_{number}_{code}_{kind}_{item.category}"
    suffix = "руда" if item.category == "R" else "порода"
    name = (f"{rule.kind_name} {number} отм.{item.horizon}{config.unit} ({suffix})"
            if rule.kind_name else "")
    return mark, name


class DraftNumbering:
    """Deterministic demonstration. No inference of pairs or approval of industry rules."""

    def assign(self, objects: list[Excavation], config: ProcessingConfig, log: IssueLog) -> None:
        linked_objects = link_pairs(objects, log)
        if not config.numbering:
            return
        angle = radians(config.bearing)
        sign = -1 if config.reverse else 1

        def position(item: Excavation) -> float:
            point = item.anchor
            assert point is not None
            east = point.east - config.start_east
            north = point.north - config.start_north
            if config.order_by == "distance":
                return sign * hypot(east, north)
            return sign * (east * sin(angle) + north * cos(angle))

        scopes: dict[tuple[str, str], list[tuple[Excavation, ...]]] = defaultdict(list)
        visited = set()
        for item in objects:
            if item.id in visited or not eligible(item) or (item.pair and item.id not in linked_objects):
                continue
            unit = linked_objects.get(item.id, (item,))
            visited.update(e.id for e in unit)
            if config.naming.style == "case" and any(case_tokens(e, config) is None for e in unit):
                refs = tuple(ref for e in unit for ref in e.refs)
                log.add("Внимание", "naming_input", "Для шаблона кейса нужны числовой горизонт, код Excel и код типа",
                        refs)
                continue
            scopes[item.horizon, item.body].append(unit)

        def order_key(unit: tuple[Excavation, ...]):
            candidate = next((e for e in unit if e.category == config.priority), None)
            anchor = candidate if candidate else min(unit, key=lambda e: (position(e), e.refs[0].row))
            category_rank = 0 if config.priority == "position" or candidate else 1
            return category_rank, position(anchor), anchor.refs[0].row

        marks = {body.name: body.mark for body in config.bodies}
        assigned: dict[str, list[Excavation]] = defaultdict(list)
        for (horizon, body), units in scopes.items():
            for number, unit in enumerate(sorted(units, key=order_key), start=config.first):
                for item in unit:
                    item.number = number
                    item.mark, item.name = trial_name(item, number, marks.get(body, body), config)
                    assigned[item.mark].append(item)

        invalid = set()
        for mark, items in assigned.items():
            if len(items) > 1:
                refs = tuple(ref for item in items for ref in item.refs)
                log.add("Ошибка", "number_conflict", f"Повторная маркировка {mark}", refs)
                for item in items:
                    invalid.update((item.id, *item.related))
        for item in objects:
            if item.id in invalid:
                item.number, item.mark, item.name = None, "", ""

