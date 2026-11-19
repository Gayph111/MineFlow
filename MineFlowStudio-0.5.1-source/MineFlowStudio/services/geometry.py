from math import dist, fsum
from typing import Protocol

from shapely.geometry import LineString, Polygon
from shapely.validation import explain_validity

from domain.models import Category, Excavation, Point3D
from services.validation import IssueLog


def path_length(points: tuple[Point3D, ...], mode: str) -> float | None:
    if len(points) < 2:
        return None
    if mode == "XY":
        return fsum(dist(a.xy, b.xy) for a, b in zip(points, points[1:]))
    if any(point.rl is None for point in points):
        return None
    xyz = [(p.east, p.north, p.rl) for p in points]
    return fsum(dist(a, b) for a, b in zip(xyz, xyz[1:]))


def contour_signature(points: tuple[Point3D, ...]):
    """Exact cyclic signature for a closed XYZ trace, independent of start and direction."""
    if len(points) < 4 or points[0] != points[-1]:
        return None
    vertices = tuple((p.east, p.north, p.rl is None, p.rl or 0.0) for p in points[:-1])
    smallest = min(vertices)
    return min(ring[i:] + ring[:i]
               for ring in (vertices, vertices[::-1])
               for i, point in enumerate(ring) if point == smallest)


def polygon_for(parts: tuple[tuple[Point3D, ...], ...]) -> tuple[Polygon | None, str]:
    if len(parts) != 1:
        return None, "Контур состоит из нескольких фрагментов"
    coords = [p.xy for p in parts[0]]
    if len(set(coords)) < 3 or coords[0] != coords[-1]:
        return None, "Контур не замкнут явно или содержит меньше трёх разных точек"
    obj = Polygon(coords)
    if not obj.is_valid:
        return None, f"Некорректный полигон: {explain_validity(obj)}"
    if obj.area == 0:
        return None, "Нулевая площадь контура"
    return obj, ""


def spatial_relation(excavation: Excavation, polygon: Polygon) -> str:
    if len(excavation.parts) != 1:
        return ""
    coords = [p.xy for p in excavation.parts[0]]
    if len(set(coords)) < 2:
        return ""
    line = LineString(coords)
    if polygon.disjoint(line):
        return "Снаружи"
    if line.crosses(polygon):
        return "Пересекает границу"
    if polygon.covers(line):
        if not line.relate_pattern(polygon, "T********"):
            return "На границе"
        return "Внутри с касанием" if line.intersects(polygon.boundary) else "Внутри"
    return "Касается границы"


class OreClassificationStrategy(Protocol):
    def assign(self, excavation: Excavation, log: IssueLog) -> Category | None: ...


class SourceClassification:
    def assign(self, excavation: Excavation, log: IssueLog) -> Category | None:
        return excavation.source_category


class GeometryClassification:
    def assign(self, excavation: Excavation, log: IssueLog) -> Category | None:
        candidate = {"Внутри": "R", "Снаружи": "P"}.get(excavation.spatial)
        if excavation.source_category and candidate and excavation.source_category != candidate:
            log.add("Ошибка", "category_conflict", "Категория в Excel расходится с пробной классификацией",
                    excavation.refs)
            return None
        return candidate

