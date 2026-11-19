from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from threading import Event
import os

from msoffcrypto.format.ooxml import OOXMLFile
from openpyxl import Workbook, load_workbook
import pytest

from domain.models import OreBody, Point3D, ProcessingConfig, SheetData
from fixtures.demo import benchmark_book, demo_book, demo_config
from services.exporter import export_workbook
from services.geometry import path_length
from services.importer import InvalidPassword, PasswordRequired, read_workbook, suggest
from services.processing import process
from services.task import Cancelled, Task


def fingerprint(result):
    return result.excavations, result.contours, result.issues


def test_geometry_xy_xyz():
    points = (Point3D(0, 0, 0), Point3D(3, 4, 12), Point3D(6, 8, 24))
    assert path_length(points, "XY") == 10
    assert path_length(points, "XYZ") == 26
    assert path_length((points[0], replace(points[1], rl=None)), "XYZ") is None
    assert path_length(points[:1], "XY") is None


def test_protected_xlsx(tmp_path):
    p = tmp_path / "simple.xlsx"
    book = Workbook()
    book.active.append(("EAST", "NORTH", "JOIN", "RL", "Комментарий"))
    book.active.append((30, 21, 7, -350, "Строка"))
    book.save(p)
    locked = tmp_path / "protected.XLSX"
    key = "fixture-password"
    with p.open("rb") as source, locked.open("wb") as target:
        OOXMLFile(source).encrypt(key, target)
    with pytest.raises(PasswordRequired):
        read_workbook(locked)
    with pytest.raises(InvalidPassword):
        read_workbook(locked, "wrong-test-password")
    assert read_workbook(locked, key).sheets == read_workbook(p).sheets


def test_demo_numbering_retains_both_pair_members():
    data, config = demo_book(), demo_config()
    result = process(data, config)
    assert len(result.excavations) == 10 and len(result.contours) == 2
    level = {e.group: e for e in result.excavations if e.horizon == "-350"}
    assert level["A"].related == (level["B"].id,)
    assert level["B"].related == (level["A"].id,)
    assert level["A"].number != level["B"].number  # distinct original axes, despite explicit link
    assert level["A"].mark.endswith("_P") and level["B"].mark.endswith("_R")
    assert level["C"].spatial == "Пересекает границу" and level["C"].number is not None
    assert level["E"].length is None and all(i.refs for i in result.issues)
    assert fingerprint(result) == fingerprint(process(data, config))
    reverse = process(data, replace(config, reverse=True))
    assert level["A"].number != next(e.number for e in reverse.excavations if e.id == level["A"].id)
    assert len({e.mark for e in result.excavations if e.mark}) == sum(bool(e.mark) for e in result.excavations)


def test_multiple_bodies_use_only_their_contour():
    data = demo_book()
    work, ring = data.sheets
    work_rows = list(work.rows)
    ring_rows = list(ring.rows)
    work_rows.extend([(12, 19, -350, "F", "Другое", None, None),
                      (13, 19, -350, "F", "Другое", None, None)])
    ring_rows.extend((x, y, -350, "ring", "Другое", None, None)
                     for x, y in ((70, 10), (80, 10), (80, 20), (70, 20), (70, 10)))
    data = replace(data, sheets=(SheetData(work.title, tuple(work_rows)), SheetData(ring.title, tuple(ring_rows))))
    setup = replace(demo_config(), classification="geometry",
                    bodies=(OreBody("Учебное", "U"), OreBody("Другое", "D")))
    result = process(data, setup)
    second = next(e for e in result.excavations if e.group == "F")
    assert second.spatial == "Снаружи" and second.mark.endswith("_D_MF_P")
    assert len([c for c in result.contours if c.horizon == "-350" and c.valid]) == 2


def test_invalid_ring_does_not_classify():
    data = demo_book()
    work, contour = data.sheets
    rows = contour.rows[:5] + contour.rows[6:]
    config = replace(demo_config(), classification="geometry")
    result = process(replace(data, sheets=(work, replace(contour, rows=rows))), config)
    assert any(i.code == "contour" for i in result.issues)
    assert all(e.category is None for e in result.excavations if e.horizon == "-350")


def test_order_conflict_has_no_guessed_length():
    data = benchmark_book(2)
    sheet = data.sheets[0]
    rows = (sheet.rows[0] + ("POINT_ORDER",), *(row + (2,) for row in sheet.rows[1:]))
    sheet = replace(sheet, rows=rows)
    result = process(replace(data, sheets=(sheet,)), ProcessingConfig(suggest(sheet), numbering=True))
    item = result.excavations[0]
    assert item.length is None and item.number is None
    assert any(i.code == "order_conflict" and [r.row for r in i.refs] == [2, 3] for i in result.issues)


def test_bad_explicit_pair_does_not_prevent_axis_numbers():
    data = demo_book()
    work = data.sheets[0]
    rows = tuple(r[:-1] + ("ошибка",) if len(r) == 7 and r[3] == "D" else r for r in work.rows)
    data = replace(data, sheets=(replace(work, rows=rows), data.sheets[1]))
    result = process(data, demo_config())
    assert all(e.number is not None and not e.related for e in result.excavations if e.group == "D")
    assert sum(i.code == "pair" for i in result.issues) == 2


@pytest.mark.parametrize("n", (402, 1000, 10000))
def test_all_synthetic_rows_retained(n):
    source = benchmark_book(n)
    config = ProcessingConfig(suggest(source.sheets[0]), numbering=True)
    result = process(source, config)
    assert len(result.excavations) == n // 2
    assert sorted(r.row for e in result.excavations for r in e.refs) == list(range(2, n + 2))
    assert len({e.mark for e in result.excavations}) == n // 2
    assert all(e.length == 1 for e in result.excavations)


def test_atomic_export_and_reimport(tmp_path):
    source = demo_book()
    config = demo_config()
    result = process(source, config)
    out = tmp_path / "MineFlow.xlsx"
    export_workbook(result, out)
    reloaded = read_workbook(out)
    assert reloaded.synthetic and reloaded.config == config
    assert fingerprint(process(reloaded, reloaded.config)) == fingerprint(result)
    with pytest.raises(ValueError, match="новый файл"):
        export_workbook(result, out, source_path=out)
    book = load_workbook(out, read_only=True)
    try:
        assert sum(1 for _ in book["MF · Строки"].values) == 1 + sum(len(e.refs) for e in result.excavations)
    finally:
        book.close()
    before = out.read_bytes()
    event = Event()

    def progress(value, _message):
        if value >= 60:
            event.set()

    with pytest.raises(Cancelled):
        export_workbook(result, out, Task(event, progress))
    assert out.read_bytes() == before


@pytest.mark.skipif(not os.environ.get("MINEFLOW_REAL_XLSX"), reason="Требуются путь и пароль к книге заказчика")
def test_case_material(tmp_path):
    path = Path(os.environ["MINEFLOW_REAL_XLSX"])
    digest = sha256(path.read_bytes()).digest()
    source = read_workbook(path, os.environ["MINEFLOW_INPUT_KEY"])
    config = ProcessingConfig(*(suggest(sheet) for sheet in source.sheets), classification="geometry", numbering=True)
    result = process(source, config)
    assert len(result.excavations) == 76
    assert sum(len(e.refs) for e in result.excavations) == 394
    assert len(result.contours) == 7 and all(c.valid for c in result.contours)
    assert sum(len(c.refs) for c in result.contours) == 1153
    assert sum(e.contour_copy for e in result.excavations) == 2
    assert sum(e.spatial == "Пересекает границу" for e in result.excavations) == 45
    assert sum(e.number is not None for e in result.excavations) == 71
    assert len(next(e.numbers for e in result.excavations if e.id=="X33"))==2
    out = tmp_path / "case.xlsx"
    export_workbook(result, out, source_path=path)
    assert sha256(path.read_bytes()).digest() == digest
    reloaded = read_workbook(out)
    assert fingerprint(process(reloaded, reloaded.config)) == fingerprint(result)

