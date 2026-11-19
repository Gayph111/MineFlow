"""Independent coordinate and workbook invariants used by the result audit."""

from collections import defaultdict
from dataclasses import dataclass
from math import isfinite, sqrt

from domain.models import ColumnMap, SheetData


def text(value):
    return str(int(value) if isinstance(value, float) and value.is_integer() else value).strip() if value is not None else ""


def value_at(row, position):
    return row[position] if position is not None and 0 <= position < len(row) else None


def decimal_value(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(text(value).replace(",", "."))
    except (ValueError, OverflowError):
        return None
    return result if isfinite(result) and abs(result) <= 1e15 else None


@dataclass(frozen=True)
class GroupAudit:
    key: str
    level: str
    body: str
    refs: tuple[int, ...]
    coords: tuple[tuple[float, float, float | None], ...]
    polyline: float | None
    chord: float | None
    unresolved: str
    pair: str
    code: str
    source_length: object
    source_category: str | None
    source_conflict: bool
    pair_conflict: bool

    @property
    def closed(self):
        return len(self.coords) >= 3 and self.coords[0][:2] == self.coords[-1][:2]


def valid_coords(row, mapping):
    x = decimal_value(value_at(row, mapping.east))
    y = decimal_value(value_at(row, mapping.north))
    z = decimal_value(value_at(row, mapping.rl))
    if x is None or y is None:
        return None
    return x, y, z


def explicit_category(value):
    token = text(value).upper()
    if token in ("P", "П", "ПОРОДА", "ГПР", "ПГР") or token.endswith("_P"):
        return "P"
    if token in ("R", "Р", "РУДА", "НР") or token.endswith("_R"):
        return "R"
    return None


def audit_groups(sheet: SheetData, mapping: ColumnMap, config) -> dict[str, GroupAudit]:
    """Regroup source rows without using the processing service or its output."""
    groups = defaultdict(list)
    for i, row in enumerate(sheet.rows[mapping.header:], mapping.header + 1):
        if not any(text(value) for value in row):
            continue
        body = text(value_at(row, mapping.body))
        level = text(value_at(row, mapping.horizon)) or text(value_at(row, mapping.rl))
        group = text(value_at(row, mapping.group)) or f"Строка {i} (без ключа)"
        groups[level, body, group].append((i, row))

    expected = {}
    dims = 3 if config.length_mode == "XYZ" else 2
    for (level, body, key), group_rows in groups.items():
        ids = tuple(index for index, _ in group_rows)
        rows = [row for _, row in group_rows]
        unresolved = ""
        if mapping.order is not None:
            order = [decimal_value(value_at(row, mapping.order)) for row in rows]
            if None in order or len(set(order)) != len(rows):
                unresolved = "неоднозначный порядок точек"
            else:
                rows = [rows[i] for i in sorted(range(len(rows)), key=order.__getitem__)]
        elif ids[-1] - ids[0] + 1 != len(ids):
            unresolved = "несмежные строки без заданного порядка"
        coords = tuple(valid_coords(row, mapping) for row in rows)
        if any(p is None for p in coords):
            unresolved = unresolved or "некорректные координаты"
        elif dims == 3 and any(p[2] is None for p in coords):
            unresolved = unresolved or "некорректная отметка RL"
        elif len(coords) < 2:
            unresolved = unresolved or "одна точка"
        polyline = chord = None
        if not unresolved:
            def segment(a, b):
                return sqrt(sum((a[k] - b[k]) ** 2 for k in range(dims)))
            polyline = sum(segment(a, b) for a, b in zip(coords, coords[1:]))
            chord = segment(coords[0], coords[-1])

        def unique(values):
            unique_values = set(values)
            return next(iter(unique_values)) if len(unique_values) == 1 else None

        source_categories = [explicit_category(value_at(row, mapping.category))
                             for row in rows if text(value_at(row, mapping.category))]
        pair_ids = {text(value_at(row, mapping.pair)) for row in rows if text(value_at(row, mapping.pair))}
        source_length = unique(value_at(row, mapping.input_length)
                               for row in rows if text(value_at(row, mapping.input_length)))
        display_body = body or (config.bodies[0].name if len(config.bodies) == 1 else "")
        expected[f"X{ids[0]}"] = GroupAudit(
            key, level, display_body, ids, tuple(p for p in coords if p is not None),
            polyline, chord, unresolved,
            unique(pair_ids) or "",
            unique(text(value_at(row, mapping.code)) for row in rows if text(value_at(row, mapping.code))) or "",
            source_length, unique(source_categories),
            None in source_categories or len(set(source_categories)) > 1, len(pair_ids) > 1,
        )
    return expected


def traces_match(a, b):
    """Compare closed sequences exactly with any start, in either traversal direction."""
    if len(a) != len(b) or len(a) < 4 or a[0] != a[-1] or b[0] != b[-1]:
        return False
    seq, ring = a[:-1], b[:-1]
    return any(seq == candidate[i:] + candidate[:i]
               for candidate in (ring, ring[::-1])
               for i, value in enumerate(candidate) if value == seq[0])

