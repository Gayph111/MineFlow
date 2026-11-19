from collections import defaultdict
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
    if group.source_category and inferred and inferred != group.source_category:
        return None
    return inferred


def audited_axis_assignment(groups, duplicates, config, axis_links=()):
    """Reconstruct ranks from the original workbook, without processing objects."""
    if not config.numbering:
        return {}, {}, set()
    coordinate_ranks = {}
    for key, g in groups.items():
        if (key in duplicates or not g.coords or not g.polyline or not g.level or g.closed
                or g.source_conflict or g.pair_conflict):
            continue
        e, n, rl = g.coords[0]
        if config.direction in ("top_bottom", "bottom_top") and rl is None and decimal_value(g.level) is None:
            continue
        x, y = e - config.start_east, n - config.start_north
        z = rl if rl is not None else decimal_value(g.level) or 0
        if config.direction == "north_south":
            coordinates = (-y, x, -z)
        elif config.direction == "south_north":
            coordinates = (y, x, -z)
        elif config.direction == "west_east":
            coordinates = (x, -y, -z)
        elif config.direction == "east_west":
            coordinates = (-x, -y, -z)
        elif config.direction == "top_bottom":
            coordinates = (-z, -y, x)
        elif config.direction == "bottom_top":
            coordinates = (z, -y, x)
        elif config.order_by == "distance":
            coordinates = (sqrt(x * x + y * y),)
        else:
            a = radians(config.bearing)
            coordinates = (x * sin(a) + y * cos(a),)
        if config.reverse:
            coordinates = tuple(-v for v in coordinates)
        priority = int(config.priority != "position" and g.source_category != config.priority)
        rank = (priority, *coordinates, g.refs[0], key)
        coordinate_ranks[key] = rank
    neighbors = defaultdict(set)
    if config.numbering_unit == "linked" and config.link_rule != "none":
        for a, b in axis_links:
            if a != b and a in coordinate_ranks and b in coordinate_ranks:
                if (groups[a].body, groups[a].level) == (groups[b].body, groups[b].level):
                    neighbors[a].add(b)
                    neighbors[b].add(a)
    blocked = {k for k, adjacent in neighbors.items()
               if len(adjacent) > 1 or any(len(neighbors[n]) > 1 for n in adjacent)}
    roots = {key: key for key in coordinate_ranks}
    for key, adjacent in neighbors.items():
        if key not in blocked:
            other = next(iter(adjacent))
            roots[key] = min(key, other)
    members = defaultdict(list)
    for key, root in roots.items():
        members[root].append(key)
    scopes = defaultdict(list)
    for root, ids in members.items():
        g = groups[ids[0]]
        scope = (g.body, g.level if config.numbering_scope == "horizon" else "")
        scopes[scope].append((min(coordinate_ranks[key] for key in ids), root, ids))
    numbers = {key: number for units in scopes.values()
               for number, (_, _, ids) in enumerate(sorted(units, key=lambda item:item[0]), config.first)
               for key in ids}
    return numbers, roots, blocked


def audited_axis_numbers(groups, duplicates, config, axis_links=()):
    return audited_axis_assignment(groups, duplicates, config, axis_links)[0]


def format_designation(g,category,number,config):
    if not category or g.source_conflict or g.pair_conflict:
        return "", ""
    rule=config.naming
    if rule.style=="case":
        depth=decimal_value(g.level)
        if depth is None or not g.code.isalnum() or not rule.kind_code.strip().isalnum():
            return "", ""
        bits=(text(abs(depth)),str(number),g.code,rule.kind_code.strip(),category)
        suffix="порода" if category=="P" else "руда"
        name=f"{rule.kind_name} {number} отм.{g.level}{config.unit} ({suffix})" if rule.kind_name else ""
    else:
        marks={body.name:body.mark for body in config.bodies}
        bits=(g.level,str(number).zfill(rule.digits),marks.get(g.body,g.body),rule.prefix,category)
        name=""
    return "_".join(bit for bit in bits if bit),name


def audited_numbering(groups, categories, duplicates, config, *, axes=None, parents=None, axis_categories=None, axis_links=None):
    """Independently verify common axis ranks and category-dependent designations."""
    by_pair = defaultdict(list)
    for key, item in groups.items():
        if item.pair:
            by_pair[item.level, item.body, item.pair].append(key)
    related = {}
    for ids in by_pair.values():
        if (len(ids) == 2 and {categories[i] for i in ids} == {"P", "R"}
                and all(eligible(groups[i], categories[i], i in duplicates) for i in ids)):
            related[ids[0]], related[ids[1]] = ids[1], ids[0]
    original = groups if axes is None else axes
    parents = parents or {key: key for key in groups}
    if axis_links is None:
        axis_links = ([(key, peer) for key, peer in related.items()]
                      if axes is None and config.link_rule == "explicit" and config.split_rule == "whole" else [])
    ranks, roots, _ = audited_axis_assignment(original, duplicates, config, axis_links)
    def designation(g,category,number):
        return format_designation(g,category,number,config)

    result, owners = {}, defaultdict(set)
    for key, g in groups.items():
        owner = parents[key]
        if owner not in ranks:
            continue
        mark, name = designation(g, categories[key], ranks[owner])
        result[key] = ranks[owner], mark, name
        if mark:
            owners[mark].add(roots[owner])
    if axes is not None and axis_categories is not None:
        for key, g in original.items():
            if key in ranks:
                mark, _ = designation(g, axis_categories[key], ranks[key])
                if mark:
                    owners[mark].add(roots[key])
    return {key: (n, "" if len(owners[mark]) > 1 else mark, "" if len(owners[mark]) > 1 else name)
            for key, (n, mark, name) in result.items()}, related

