from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Literal

from domain.case_reference import CaseReference

Value = str | int | float | bool | date | datetime | time | timedelta | None
Category = Literal["P", "R"]
Severity = Literal["Ошибка", "Внимание", "Информация"]


@dataclass(frozen=True, slots=True)
class Point3D:
    east: float
    north: float
    rl: float | None

    @property
    def xy(self) -> tuple[float, float]:
        return self.east, self.north


@dataclass(frozen=True, slots=True)
class RowRef:
    sheet: str
    row: int

    def __str__(self) -> str:
        return f"{self.sheet}!{self.row}"


@dataclass(frozen=True, slots=True)
class SheetData:
    title: str
    rows: tuple[tuple[Value, ...], ...]

    def values(self, row: int) -> tuple[Value, ...]:
        return self.rows[row - 1]


@dataclass(frozen=True, slots=True)
class WorkbookData:
    name: str
    sheets: tuple[SheetData, ...]
    synthetic: bool = False
    origin: str | None = None
    config: ProcessingConfig | None = None
    xlsx: bytes = field(default=b"", repr=False, compare=False)

    def sheet(self, title: str) -> SheetData:
        return next(sheet for sheet in self.sheets if sheet.title == title)


@dataclass(frozen=True, slots=True)
class ColumnMap:
    sheet: str
    header: int = 1
    east: int | None = None
    north: int | None = None
    rl: int | None = None
    group: int | None = None
    horizon: int | None = None
    body: int | None = None
    category: int | None = None
    order: int | None = None
    pair: int | None = None
    input_length: int | None = None
    code: int | None = None


@dataclass(frozen=True, slots=True)
class OreBody:
    name: str
    mark: str


@dataclass(frozen=True, slots=True)
class NamingRule:
    prefix: str = "MF"
    digits: int = 2
    style: Literal["internal", "case"] = "internal"
    kind_code: str = ""
    kind_name: str = ""


@dataclass(frozen=True, slots=True)
class ProcessingConfig:
    working: ColumnMap
    contour: ColumnMap | None = None
    bodies: tuple[OreBody, ...] = ()
    naming: NamingRule = field(default_factory=NamingRule)
    length_mode: Literal["XY", "XYZ"] = "XY"
    unit: str = ""
    classification: Literal["source", "geometry"] = "source"
    numbering: bool = False
    order_by: Literal["projection", "distance"] = "projection"
    start_east: float = 0
    start_north: float = 0
    bearing: float = 0
    reverse: bool = False
    priority: Literal["position", "P", "R"] = "position"
    first: int = 1
    split_rule: Literal["contour", "whole"] = "contour"
    link_rule: Literal["continuity", "explicit", "none"] = "continuity"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: Severity
    code: str
    message: str
    refs: tuple[RowRef, ...]


@dataclass(slots=True)
class Excavation:
    id: str
    group: str
    horizon: str
    body: str
    refs: tuple[RowRef, ...]
    parts: tuple[tuple[Point3D, ...], ...]
    source_category: Category | None = None
    category: Category | None = None
    spatial: str = ""
    pair: str = ""
    related: tuple[str, ...] = ()
    length: float | None = None
    endpoint_length: float | None = None
    code: str = ""
    name: str = ""
    input_length: Value = None
    contour_copy: bool = False
    numbering_blocked: bool = False
    number: int | None = None
    mark: str = ""
    reference: CaseReference | None = None
    axis_id: str = ""
    ordinal: int = 0
    review: str = ""
    category_basis: str = ""

    @property
    def display_mark(self) -> str:
        return self.reference.mark if self.reference else self.mark

    @property
    def display_name(self) -> str:
        return self.reference.name if self.reference else self.name

    @property
    def display_number(self) -> int | None:
        return self.reference.number if self.reference else self.number

    @property
    def designation_basis(self) -> str:
        return "Из примера" if self.reference else "Пробное" if self.mark else "Не присвоено"

    @property
    def closed(self) -> bool:
        return any(len(part) >= 3 and part[0].xy == part[-1].xy for part in self.parts)

    @property
    def anchor(self) -> Point3D | None:
        return next((part[0] for part in self.parts if part), None)


@dataclass(frozen=True, slots=True)
class Contour:
    group: str
    horizon: str
    body: str
    refs: tuple[RowRef, ...]
    parts: tuple[tuple[Point3D, ...], ...]
    valid: bool


@dataclass(frozen=True, slots=True)
class SegmentLink:
    rock: str
    ore: str
    basis: str


@dataclass(slots=True)
class ProcessingResult:
    source: WorkbookData
    config: ProcessingConfig
    excavations: tuple[Excavation, ...]
    contours: tuple[Contour, ...]
    issues: tuple[ValidationIssue, ...]
    elapsed: float
    segments: tuple[Excavation, ...] = ()
    links: tuple[SegmentLink, ...] = ()

