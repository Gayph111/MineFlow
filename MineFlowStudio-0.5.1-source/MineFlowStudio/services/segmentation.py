"""Split survey axes into contiguous parts without moving original vertices."""

from collections import Counter, defaultdict
from math import fsum

from shapely import get_coordinates
from shapely.geometry import LineString, Point

from domain.models import Excavation, Point3D, SegmentLink
from services.geometry import path_length
from services.numbering import link_pairs
from services.physical_axes import main_direction, partition_paths
from services.validation import IssueLog

LOCATIONS = {"P": "Снаружи", "R": "Внутри", None: "На границе"}


def _interpolate(a, b, fraction):
    if fraction == 0:
        return a
    if fraction == 1:
        return b
    rl = a.rl + (b.rl - a.rl) * fraction if a.rl is not None and b.rl is not None else None
    return Point3D(a.east + (b.east - a.east) * fraction, a.north + (b.north - a.north) * fraction, rl)


def split_polyline(points, polygon):
    """Return travel-ordered (P/R/None, points), preserving a shared cut on both sides."""
    boundary = polygon.boundary
    runs = []
    for a, b in zip(points, points[1:]):
        fractions = [0.0, 1.0]
        dx, dy = b.east - a.east, b.north - a.north
        if dx or dy:
            edge = LineString((a.xy, b.xy))
            for x, y in get_coordinates(edge.intersection(boundary)):
                t = (x - a.east) / dx if abs(dx) >= abs(dy) else (y - a.north) / dy
                if 1e-12 < t < 1 - 1e-12:
                    fractions.append(float(t))
        cuts = sorted(set(fractions))
        vertices = [_interpolate(a, b, t) for t in cuts]
        for start, end in zip(vertices, vertices[1:]):
            mid = Point((start.east + end.east) / 2, (start.north + end.north) / 2)
            category = "R" if polygon.contains(mid) else "P" if polygon.disjoint(mid) else None
            if runs and runs[-1][0] == category:
                runs[-1][1].append(end)
            else:
                runs.append((category, [start, end]))
    return [(category, tuple(vertices)) for category, vertices in runs]


def _from_axis(axis, config, polygon):
    if axis.contour_copy:
        return []
    if axis.length is None or axis.closed:
        reason = ("Замкнутая ось требует подтверждения типа" if axis.closed else
                  "Для длины не хватает координат или заданный порядок точек неоднозначен")
        return [(None, axis.parts, axis.spatial, reason, "")]
    if config.split_rule == "whole":
        label = "Из Excel" if config.classification == "source" and axis.category else "По положению" if axis.category else ""
        reason = "" if axis.category else "Категория оси отсутствует или не определена"
        return [(axis.category, axis.parts, axis.spatial, reason, label)]
    if polygon is None:
        return [(None, axis.parts, axis.spatial, "Для тела и горизонта нет однозначного валидного контура", "")]
    return [(cat, (points,), LOCATIONS[cat],
             "" if cat else "Фрагмент лежит на границе контура", "Геометрия контура" if cat else "")
            for cat, points in split_polyline(axis.parts[0], polygon)]


def build_segments(axes, polygons, config, log: IssueLog, task):
    segments = []
    proposals = []
    directions={}
    if config.numbering_unit=="axis":
        scopes=defaultdict(list)
        for axis in axes:
            scopes[axis.horizon,axis.body].append(axis)
        directions={key:main_direction(items,config) for key,items in scopes.items()}
    for axis in axes:
        direction=directions.get((axis.horizon,axis.body))
        task.check()
        source_parts = _from_axis(axis, config, polygons.get(axis.id))
        parts=[]
        for cat,paths,spatial,reason,basis in source_parts:
            if direction is not None and axis.length is not None and not axis.closed:
                parts.extend((cat,runs,spatial,reason,basis,role)
                             for role,runs in partition_paths(paths,direction,config.line_angle))
            else:
                parts.append((cat,paths,spatial,reason,basis,"unknown" if direction else "source"))
        current = []
        for ordinal, (cat, paths, spatial, reason, basis, role) in enumerate(parts, 1):
            length = path_length(paths[0], config.length_mode) if len(paths) == 1 and axis.length is not None else None
            ends = path_length((paths[0][0], paths[0][-1]), config.length_mode) if length is not None else None
            item = Excavation(f"{axis.id}.{ordinal}", axis.group, axis.horizon, axis.body, axis.refs, paths,
                              source_category=axis.source_category, category=cat, spatial=spatial,
                              length=length, endpoint_length=ends, code=axis.code,
                              numbering_blocked=not cat or length is None or axis.numbering_blocked,
                              axis_id=axis.id, ordinal=ordinal, review=reason, category_basis=basis,
                              line_role=role, numbering_blocked_source=axis.numbering_blocked)
            if config.link_rule == "explicit" and len(parts) == 1:
                item.pair = axis.pair
            if reason and axis.length is not None and not (config.split_rule=="whole" and not cat):
                log.add("Внимание", "segment_review", f"{item.id} · {reason}", axis.refs)
            current.append(item)
        if len(current) > 1 and axis.length is not None:
            total = fsum(item.length for item in current if item.length is not None)
            if abs(total - axis.length) > max(1e-8, abs(axis.length) * 1e-12):
                raise ValueError(f"{axis.id}: сумма длин участков расходится с длиной оси")
        if config.link_rule == "continuity":
            proposals.extend((a, b) for a, b in zip(current, current[1:])
                             if {a.category, b.category} == {"P", "R"}
                             and a.parts[0][-1] == b.parts[0][0] and a.length and b.length
                             and not (a.numbering_blocked or b.numbering_blocked))
        segments.extend(current)

    degree = Counter(item.id for edge in proposals for item in edge)
    ambiguous = {}
    for first, second in proposals:
        if degree[first.id] == degree[second.id] == 1:
            first.pair = second.pair = f"{first.axis_id}:{first.ordinal}–{second.ordinal}"
        else:
            ambiguous[first.id], ambiguous[second.id] = first, second
    for item in ambiguous.values():
        item.review = "У геометрического перехода несколько кандидатов для пары"
        log.add("Внимание", "ambiguous_link", f"{item.id} · {item.review}", item.refs)

    link_pairs(segments, log)
    by_id = {item.id: item for item in segments}
    basis = "Непрерывность исходной оси" if config.link_rule == "continuity" else "Идентификатор пары из Excel"
    links = tuple(SegmentLink(item.id, peer, basis) for item in segments if item.category == "P"
                  for peer in item.related if peer in by_id)
    return tuple(segments), links

