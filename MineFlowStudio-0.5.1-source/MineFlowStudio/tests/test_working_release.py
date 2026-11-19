from dataclasses import replace
from hashlib import sha256
from collections import Counter
from pathlib import Path
import os

from openpyxl import load_workbook
from shapely.geometry import Polygon
import pytest

from domain.models import Point3D, ProcessingConfig, SheetData
from fixtures.demo import benchmark_book, demo_book
from services.delivery_audit import audit_delivery, render_review
from services.importer import read_workbook, suggest
from services.processing import process
from services.project_files import ProjectFile, read_project, write_project
from services.publication import publish
from services.segmentation import split_polyline
from services.workbook_delivery import save_delivery

REAL = os.environ.get("MINEFLOW_REAL_XLSX")


def test_geometry_interpolates_xyz_and_keeps_original_vertices():
    diamond = Polygon(((0, 1), (1, 0), (2, 1), (1, 2)))
    a, b, c = Point3D(-1, 1, 0), Point3D(1, 1, 3), Point3D(3, 1, 8)
    items = split_polyline((a, b, c), diamond)
    assert items == [
        ("P", (a, Point3D(0, 1, 1.5))),
        ("R", (Point3D(0, 1, 1.5), b, Point3D(2, 1, 5.5))),
        ("P", (Point3D(2, 1, 5.5), c)),
    ]
    # An interior run on the boundary remains unclassified; touching a corner makes no ore run.
    square = Polygon(((0, 0), (1, 0), (1, 1), (0, 1)))
    edge = split_polyline((Point3D(-1, 0, 0), Point3D(2, 0, 0)), square)
    assert [category for category, _ in edge] == ["P", None, "P"]
    touching = split_polyline((Point3D(-1, 1, 0), Point3D(1, -1, 0)), square)
    assert [category for category, _ in touching] == ["P"]


@pytest.mark.skipif(not REAL, reason="Требуется исходная книга")
@pytest.mark.parametrize("mode", ("XY", "XYZ"))
def test_case_workbook_is_independently_verified(tmp_path, mode):
    source_path = Path(REAL)
    baseline = sha256(source_path.read_bytes()).digest()
    source = read_workbook(source_path, os.environ["MINEFLOW_INPUT_KEY"])
    config = ProcessingConfig(*(suggest(s) for s in source.sheets), length_mode=mode, numbering_unit="source")
    result = process(source, config)
    assert len(result.excavations) == 76 and len(result.segments) == 126
    assert Counter(e.category for e in result.segments) == {"P": 72, "R": 52, None: 2}
    assert len(result.links) == 38
    assert not any(s.number or s.mark for s in result.segments)
    assert len([e for e in result.segments if "несколько кандидатов" in e.review]) == 21
    assert next(e.reference.mark for e in result.excavations if e.group == "1538") == "350_5_N_OBD_P"
    assert [s.category for s in result.segments if s.group == "1538"] == ["P", "R"]
    path = tmp_path / "result.xlsx"
    report, saved = publish(result, path, source_path, None)
    assert saved and report.counts["FAIL"] == 0
    assert report.lengths == 74 and report.segments == 126 and report.links == 38
    assert sha256(source_path.read_bytes()).digest() == baseline
    assert read_workbook(path).sheets == source.sheets
    assert (tmp_path / "result_UNVERIFIED_CASES.md").is_file()
    assert len([f for f in report.findings if f.code == "ambiguous_link"]) == 21
    assert "несколько кандидатов" in render_review(report)
    workbook = load_workbook(path)
    assert workbook.active.title == "Участки"
    workbook["Участки"]["I2"].value += 2
    assert workbook["Связи участков"].max_row > 3
    workbook["Связи участков"]["B2"] = workbook["Связи участков"]["B3"].value
    workbook.save(path)
    faults = {f.code for f in audit_delivery(source, config, path).findings if f.status == "FAIL"}
    assert {"section_geometry", "links"} <= faults


def test_explicit_links_respect_source_and_mode(tmp_path):
    data = demo_book()
    cfg = ProcessingConfig(*(suggest(s) for s in data.sheets), split_rule="whole", link_rule="explicit",
                           numbering=True, numbering_unit="source")
    result = process(data, cfg)
    assert len(result.links) == 2
    assert all(link.basis == "Идентификатор пары из Excel" for link in result.links)
    by_id = {e.id: e for e in result.segments}
    assert all(by_id[p.rock].number != by_id[p.ore].number for p in result.links)
    assert all(s.number == next(a.number for a in result.excavations if a.id == s.axis_id) for s in result.segments)
    target = tmp_path / "pair.xlsx"
    save_delivery(result, target)
    assert audit_delivery(data, cfg, target).counts["FAIL"] == 0
    assert not process(data, replace(cfg, link_rule="none")).links


@pytest.mark.parametrize("rows", (200, 400, 1000, 5000))
def test_numbering_scales_to_large_sources(rows):
    source = benchmark_book(rows)
    cfg = ProcessingConfig(suggest(source.sheets[0]), split_rule="whole", link_rule="none", numbering=True)
    result = process(source, cfg)
    assert sum(len(e.refs) for e in result.excavations) == rows
    assert len(result.segments) == rows // 2
    assert len({s.mark for s in result.segments if s.mark}) == rows // 2
    assert all(s.length == 1 for s in result.segments)


def test_project_round_trip_keeps_settings_and_relative_source(tmp_path):
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"known test file")
    config = ProcessingConfig(suggest(demo_book().sheets[0]), split_rule="whole",
                              link_rule="explicit", numbering=True, first=7, bearing=122.5)
    path = tmp_path / "final.mineflow.json"
    write_project(ProjectFile(path, source, config))
    restored = read_project(path)
    assert restored.source == source.resolve() and restored.config == config
    assert '"source": "source.xlsx"' in path.read_text(encoding="utf-8")
    assert "password" not in path.read_text(encoding="utf-8").lower()

