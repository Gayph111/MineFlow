"""Verbatim, attributable example from the customer materials."""

from dataclasses import dataclass
from math import isclose


@dataclass(frozen=True)
class CaseReference:
    join: str
    horizon: str
    body: str
    code: str
    east_range: tuple[float, float]
    north_range: tuple[float, float]
    number: int
    mark: str
    name: str
    work_kind: str
    displayed_length: float
    calculated_length: float
    citation: str


SUPPLIED_EXAMPLE = CaseReference(
    join="1538", horizon="-350", body="НовоИТишное2026", code="N",
    east_range=(48813.327380, 48907.737330), north_range=(49255.495330, 49255.583240),
    number=5, mark="350_5_N_OBD_P", name="Орт буро-доставочный 5 отм.-350м (порода)",
    work_kind="ГПР", displayed_length=94.4, calculated_length=94.409991,
    citation="сопроводиловка.pptx, слайды 1–2",
)


def from_customer_example(item):
    known = SUPPLIED_EXAMPLE
    if (item.group, item.horizon, item.body, item.code) != (known.join, known.horizon, known.body, known.code):
        return None
    if len(item.parts) != 1 or item.length is None:
        return None
    path = item.parts[0]
    if not all(p.rl == -350 for p in path):
        return None
    east, north = (p.east for p in path), (p.north for p in path)
    east, north = tuple(east), tuple(north)
    observed = min(east), max(east), min(north), max(north)
    expected = known.east_range + known.north_range
    return known if all(isclose(a, b, rel_tol=0, abs_tol=5e-7) for a, b in zip(observed, expected)) else None

