from dataclasses import replace
from collections import defaultdict

from openpyxl import load_workbook
import pytest

from domain.models import ProcessingConfig, SheetData, WorkbookData
from services.delivery_audit import audit_delivery
from services.importer import suggest, config_from_dict
from services.processing import process
from services.project_files import ProjectFile, read_project, write_project
from services.workbook_delivery import save_delivery


def sample():
    head = ("EAST", "NORTH", "RL", "JOIN", "РУДНОЕ_ТЕЛО")
    axes, rings = [head], [head]
    # Deliberately reversed source-row order; two bodies and two elevations.
    for body in ("Body A", "Body B"):
        for level in (-500, -350):
            for join, north in (("South", 2), ("North", 8), ("Middle", 5)):
                axes.extend((x, north, level, join, body) for x in (-5, 15))
            rings.extend((x, y, level, "ring", body) for x, y in ((0,0),(10,0),(10,10),(0,10),(0,0)))
    book = WorkbookData("Test", (SheetData("axes", tuple(axes)), SheetData("rings", tuple(rings))))
    return book, ProcessingConfig(*(suggest(s) for s in book.sheets), numbering=True,
                                  direction="north_south")


@pytest.mark.parametrize("direction,first,last", (
    ("north_south", "North", "South"), ("south_north", "South", "North"),
    ("top_bottom", "-350", "-500"), ("bottom_top", "-500", "-350"),
))
@pytest.mark.parametrize("scope", ("horizon", "body"))
def test_one_rank_for_all_parts_and_independent_workbook_audit(tmp_path, direction, first, last, scope):
    data, cfg = sample()
    cfg = replace(cfg, direction=direction, numbering_scope=scope, first=7)
    result = process(data, cfg)
    assert len(result.excavations) == 12 and len(result.segments) == 36
    owners = {e.id: e for e in result.excavations}
    assert all(s.number == owners[s.axis_id].number for s in result.segments)
    assert all(len([s for s in result.segments if s.axis_id == e.id]) == 3 for e in owners.values())
    groups = defaultdict(list)
    for e in result.excavations:
        groups[e.body, e.horizon if scope == "horizon" else ""].append(e)
    for records in groups.values():
        ordered = sorted(records, key=lambda e: e.number)
        assert [e.number for e in ordered] == list(range(7, 7+len(records)))
        if direction in ("north_south", "south_north"):
            assert ordered[0].group == first and ordered[-1].group == last
        elif scope == "body":
            assert ordered[0].horizon == first and ordered[-1].horizon == last
    target = tmp_path / "result.xlsx"
    save_delivery(result, target)
    report = audit_delivery(data, cfg, target)
    assert not report.counts["FAIL"], [f for f in report.findings if f.status == "FAIL"]
    # P→R→P produces the same axis number and intentional same-category designation.
    p, r, p2 = result.segments[:3]
    assert p.number == r.number == p2.number and p.mark == p2.mark != r.mark
    workbook = load_workbook(target)
    workbook["Участки"]["R2"] = 123456
    workbook["Оси"]["O2"] = 654321
    workbook.save(target)
    codes = {f.code for f in audit_delivery(data, cfg, target).findings if f.status == "FAIL"}
    assert {"number_by_rule", "axis_number"} <= codes


@pytest.mark.parametrize("direction,expected", (("west_east", ["West","Middle","East"]),
                                               ("east_west", ["East","Middle","West"])))
def test_east_west_directions(direction, expected):
    data, cfg = sample()
    sheet = data.sheets[0]
    head = sheet.rows[0]
    rows = [head]
    for name, east in (("Middle", 5), ("East", 9), ("West", 1)):
        rows.extend(((east, 1, -350, name, "A"), (east, 9, -350, name, "A")))
    data = replace(data, sheets=(replace(sheet, rows=tuple(rows)),))
    result = process(data, replace(cfg, contour=None, direction=direction, split_rule="whole"))
    assert [e.group for e in sorted(result.excavations, key=lambda e:e.number)] == expected


def test_numbering_does_not_depend_on_links_or_split_mode():
    data, cfg = sample()
    baseline = process(data, cfg)
    for split, links in (("whole","none"), ("contour","none"), ("contour","explicit")):
        result = process(data, replace(cfg, split_rule=split, link_rule=links))
        assert [(e.id,e.number) for e in result.excavations] == [(e.id,e.number) for e in baseline.excavations]
        assert [e.parts for e in result.excavations] == [e.parts for e in baseline.excavations]


def test_settings_roundtrip_and_old_project_defaults(tmp_path):
    from dataclasses import asdict
    data, cfg = sample()
    cfg = replace(cfg, numbering_scope="body", direction="bottom_top")
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"test")
    project = tmp_path / "test.mineflow.json"
    write_project(ProjectFile(project, source, cfg))
    assert read_project(project).config == cfg
    old = asdict(cfg)
    del old["numbering_scope"], old["direction"], old["numbering_unit"]
    loaded = config_from_dict(old)
    assert loaded.numbering_scope == "horizon" and loaded.direction == "custom" and loaded.numbering_unit == "axis"



def test_horizontal_ties_use_numeric_horizon_when_rl_is_missing(tmp_path):
    from services.importer import suggest
    head = ("EAST", "NORTH", "RL", "JOIN", "РУДНОЕ_ТЕЛО", "ГОРИЗОНТ")
    rows = [head]
    for horizon in (-500, -350):
        rows.extend(((0, 2, None, str(horizon), "A", horizon),
                     (10, 2, None, str(horizon), "A", horizon)))
    data = WorkbookData("No RL", (SheetData("axes", tuple(rows)),))
    cfg = ProcessingConfig(suggest(data.sheets[0]), numbering=True, numbering_scope="body",
                           direction="north_south", split_rule="whole")
    result = process(data, cfg)
    assert [e.horizon for e in sorted(result.excavations, key=lambda e:e.number)] == ["-350", "-500"]
    target = tmp_path / "no_rl.xlsx"
    save_delivery(result, target)
    assert audit_delivery(data, cfg, target).counts["FAIL"] == 0
