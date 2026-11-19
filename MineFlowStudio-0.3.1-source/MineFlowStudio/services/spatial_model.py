"""Exact, shared world coordinates for CAD display, independent of rendering."""

from dataclasses import dataclass

from domain.models import ProcessingResult

XYZ = tuple[float, float, float]
Path3D = tuple[XYZ, ...]


@dataclass(frozen=True)
class Shape3D:
    id: str
    horizon: str
    body: str
    paths: tuple[Path3D, ...]
    unplaced: int


def _literal_paths(parts):
    paths = []
    unplaced = 0
    for part in parts:
        run = []
        for p in part:
            if p.rl is None:
                unplaced += 1
                if run:
                    paths.append(tuple(run))
                    run = []
            else:
                run.append((p.east, p.north, p.rl))
        if run:
            paths.append(tuple(run))
    return tuple(paths), unplaced


def build_spatial_model(result: ProcessingResult) -> tuple[tuple[Shape3D, ...], tuple[Shape3D, ...]]:
    return (
        tuple(Shape3D(e.id, e.horizon, e.body, *_literal_paths(e.parts)) for e in result.excavations),
        tuple(Shape3D(f"Контур {c.refs[0].row}", c.horizon, c.body, *_literal_paths(c.parts))
              for c in result.contours),
    )

