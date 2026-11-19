from collections import Counter, defaultdict
from math import cos, radians, sin, sqrt

from services.audit_geometry import decimal_value, text


def eligible(group, category, outline):
    return bool(category and group.level and group.polyline and not group.closed and not outline
                and not group.source_conflict and not group.pair_conflict)


def category_for(group, result_row, contour_copy, config):
    if contour_copy or group.closed:
        return None
    if config.classification == "source":
        return group.source_category
    inferred = {"Внутри": "R", "Снаружи": "P"}.get(result_row.get("Положение"))
    if group.source_category and inferred != group.source_category:
        return None
    return inferred


def coordinates_rank(group, config):
    east, north, _ = group.coords[0]
    x, y = east - config.start_east, north - config.start_north
    if config.order_by == "distance":
        estimate = sqrt(x * x + y * y)
    else:
        angle = radians(config.bearing)
        estimate = x * sin(angle) + y * cos(angle)
    return -estimate if config.reverse else estimate


def audited_numbering(groups, categories, duplicates, config):
    """Independently determine expected technical draft ranks and explicit links."""
    by_pair = defaultdict(list)
    for key, item in groups.items():
        if item.pair:
            by_pair[item.level, item.body, item.pair].append(key)
    related = {}
    for ids in by_pair.values():
        if (len(ids) == 2 and {categories[i] for i in ids} == {"P", "R"}
                and all(eligible(groups[i], categories[i], i in duplicates) for i in ids)):
            related[ids[0]], related[ids[1]] = ids[1], ids[0]

    if not config.numbering:
        return {}, related

    scopes = defaultdict(list)
    visited = set()
    rule = config.naming

    def case_available(group):
        depth = decimal_value(group.level)
        return depth is not None and group.code.isalnum() and rule.kind_code.strip().isalnum()

    for key, group in groups.items():
        if key in visited or not eligible(group, categories[key], key in duplicates):
            continue
        partner = related.get(key)
        unit = [key, partner] if partner else [key]
        if (group.pair and not partner) or (rule.style == "case" and not all(case_available(groups[i]) for i in unit)):
            continue
        visited.update(unit)
        rank = min((int(config.priority not in ("position", categories[i])),
                    coordinates_rank(groups[i], config), groups[i].refs[0]) for i in unit)
        scopes[group.level, group.body].append((rank, unit))

    codes = {body.name: body.mark for body in config.bodies}
    markings = {}
    for (level, body), records in scopes.items():
        for number, (_, unit) in enumerate(sorted(records, key=lambda record: record[0]), config.first):
            for key in unit:
                group, category = groups[key], categories[key]
                if rule.style == "case":
                    parts = (text(abs(decimal_value(level))), str(number), group.code, rule.kind_code.strip(), category)
                    suffix = "порода" if category == "P" else "руда"
                    name = f"{rule.kind_name} {number} отм.{level}{config.unit} ({suffix})" if rule.kind_name else ""
                else:
                    parts = (level, str(number).zfill(rule.digits), codes.get(body, body), rule.prefix, category)
                    name = ""
                markings[key] = (number, "_".join(part for part in parts if part), name)
    counts = Counter(mark for _, mark, _ in markings.values())
    conflicts = {key for key, (_, mark, _) in markings.items() if counts[mark] > 1}
    conflicts |= {related[key] for key in conflicts if key in related}
    return {key: value for key, value in markings.items() if key not in conflicts}, related

