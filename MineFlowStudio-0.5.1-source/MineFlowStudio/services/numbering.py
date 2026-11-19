from collections import defaultdict
from math import cos, hypot, radians, sin

from domain.models import Excavation, ProcessingConfig
from services.validation import IssueLog, as_text, numeric


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



def axis_order(item: Excavation, config: ProcessingConfig):
    """The first original point is the stable position of an entire excavation."""
    p = item.anchor
    x, y = p.east - config.start_east, p.north - config.start_north
    try:
        z = p.rl if p.rl is not None else numeric(item.horizon)
    except ValueError:
        z = 0
    directions = {
        "north_south": (-y, x, -z), "south_north": (y, x, -z),
        "west_east": (x, -y, -z), "east_west": (-x, -y, -z),
        "top_bottom": (-z, -y, x), "bottom_top": (z, -y, x),
    }
    if config.direction in directions:
        rank = directions[config.direction]
    elif config.order_by == "distance":
        rank = (hypot(x, y),)
    else:
        a = radians(config.bearing)
        rank = (x * sin(a) + y * cos(a),)
    if config.reverse:
        rank = tuple(-v for v in rank)
    category_rank = int(config.priority != "position" and item.source_category != config.priority)
    return category_rank, *rank, item.refs[0].row, item.id


def axis_number_groups(axes, segments, config):
    """Only an established one-to-one P/R link can merge two original axes."""
    by_id = {e.id: e for e in axes}
    roots = {e.id: e.id for e in axes}
    if config.numbering_unit != "linked" or config.link_rule == "none":
        return roots, set()
    segments_by_id = {e.id: e for e in segments}
    neighbors = defaultdict(set)
    for e in segments:
        for peer_id in e.related:
            peer = segments_by_id.get(peer_id)
            a, b = e.axis_id, peer.axis_id if peer else ""
            if not peer or a == b or a not in by_id or b not in by_id:
                continue
            if (by_id[a].horizon, by_id[a].body) != (by_id[b].horizon, by_id[b].body):
                continue
            if {e.category, peer.category} != {"P", "R"}:
                continue
            neighbors[a].add(b)
            neighbors[b].add(a)
    ambiguous = {key for key, peers in neighbors.items()
                 if len(peers) != 1 or any(len(neighbors[p]) != 1 for p in peers)}
    for a, peers in neighbors.items():
        if a not in ambiguous:
            b = next(iter(peers))
            roots[a] = roots[b] = min(a, b)
    return roots, ambiguous


def assign_axis_numbers(axes, segments, config: ProcessingConfig, log: IssueLog):
    """One rank per entire original axis, optionally shared by an unambiguous linked pair."""
    for item in (*axes, *segments):
        item.number, item.mark, item.name, item.number_group, item.numbers = None, "", "", "", ()
    if not config.numbering:
        return
    if config.numbering_unit == "axis":
        from services.physical_axes import assign_physical_numbers
        assign_physical_numbers(axes,segments,config,axis_order,assign_designations,log)
        return
    eligible_axes = []
    for axis in axes:
        if (not axis.anchor or not axis.horizon or not axis.length or axis.closed
                or axis.contour_copy or axis.numbering_blocked):
            continue
        # Cardinal vertical ordering needs a known numeric elevation.
        if config.direction in ("top_bottom", "bottom_top") and axis.anchor.rl is None:
            try:
                numeric(axis.horizon)
            except ValueError:
                log.add("Внимание", "numbering_elevation", "Для порядка сверху вниз нужен числовой RL или горизонт", axis.refs)
                continue
        eligible_axes.append(axis)
    roots, ambiguous = axis_number_groups(eligible_axes, segments, config)
    for axis in eligible_axes:
        if axis.id in ambiguous:
            log.add("Внимание", "numbering_group", "У оси несколько партнёров: общий номер не назначен, ось нумеруется отдельно", axis.refs)
    units = defaultdict(list)
    for axis in eligible_axes:
        units[roots[axis.id]].append(axis)
    scopes = defaultdict(list)
    for root, members in units.items():
        first = members[0]
        scope = first.body, first.horizon if config.numbering_scope == "horizon" else ""
        scopes[scope].append((min(axis_order(e, config) for e in members), root, members))
    owners = {}
    for records in scopes.values():
        for number, (_, root, members) in enumerate(sorted(records, key=lambda r:r[0]), config.first):
            for axis in members:
                owners[axis.id] = number
    for item in (*axes,*segments):
        owner=item.axis_id or item.id
        item.number=owners.get(owner)
        item.number_group=roots.get(owner,"") if item.number is not None else ""
        item.numbers=(item.number,) if item.number is not None else ()
    assign_designations(axes,segments,config,log)


def assign_designations(axes,segments,config,log):
    body_marks = {body.name: body.mark for body in config.bodies}
    assigned = defaultdict(list)
    for item in (*axes, *segments):
        if item.number is None or not item.category or item.numbering_blocked:
            continue
        if config.naming.style == "case" and case_tokens(item, config) is None:
            log.add("Внимание", "naming_input",
                    "Номер оси рассчитан. Для обозначения нужны числовой горизонт, CODE и код типа", item.refs)
            continue
        item.mark, item.name = trial_name(item, item.number, body_marks.get(item.body, item.body), config)
        assigned[item.mark].append(item)
    # Several same-category pieces may intentionally have the same axis designation.
    # A designation shared by different original axes is still a naming conflict.
    for mark, items in assigned.items():
        if len({e.number_group for e in items}) > 1:
            log.add("Ошибка", "number_conflict", f"Обозначение разных осей совпало: {mark}",
                    tuple(dict.fromkeys(ref for e in items for ref in e.refs)))
            for item in items:
                item.mark, item.name = "", ""
