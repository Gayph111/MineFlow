from dataclasses import replace
from pathlib import Path
import os

from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText
import pytest

from domain.models import NamingRule, OreBody, ProcessingConfig, SheetData
from fixtures.demo import demo_book, demo_config
from services.exporter import export_workbook
from services.importer import read_workbook, suggest
from services.processing import process
from services.result_audit import audit_export


def test_original_types_and_formula_survive_export(tmp_path):
    source_path, out = tmp_path / "input.xlsx", tmp_path / "output.xlsx"
    book = Workbook()
    ws = book.active
    ws.title = "Axes"
    ws.append(("EAST", "NORTH", "RL", "JOIN", "Formula", "Text", "Blank text", "Excel error"))
    ws.append((2.5, 10, -350, "A", "=A2+1", "=text", CellRichText([""]), "#N/A"))
    ws["F2"].data_type = "s"
    ws["A2"].number_format = "0.000"
    ws.append((3.5, 11, -350, "A"))
    book.save(source_path)
    source = read_workbook(source_path)
    cfg = ProcessingConfig(suggest(source.sheets[0]))
    export_workbook(process(source, cfg), out)
    output = load_workbook(out)
    ws = output["Axes"]
    assert [(ws[c].value, ws[c].data_type) for c in ("E2", "F2", "G2", "H2")] == [
        ("=A2+1", "f"), ("=text", "s"), ("", "s"), ("#N/A", "e")
    ]
    assert ws["A2"].number_format == "0.000"
    assert audit_export(source, cfg, out).counts["FAIL"] == 0


def test_audit_detects_incorrect_workbook(tmp_path):
    data, cfg = demo_book(), demo_config()
    target = tmp_path / "check.xlsx"
    export_workbook(process(data, cfg), target)
    audit = audit_export(data, cfg, target)
    assert audit.counts["FAIL"] == 0
    assert audit.counts["UNVERIFIED"] > 0
    damaged = load_workbook(target)
    damaged["MF · Расчёт"]["H2"] = 999
    damaged["MF · Расчёт"]["M3"] = damaged["MF · Расчёт"]["M2"].value
    damaged["MF · Строки"].delete_rows(3)
    damaged[data.sheets[0].title]["A2"] = 700
    damaged.save(target)
    findings = [f for f in audit_export(data, cfg, target).findings if f.status == "FAIL"]
    assert {"work_refs", "source_cells", "length", "mark_duplicates", "group_value"} <= {f.code for f in findings}


def test_reference_book_compares_every_number_and_name(tmp_path):
    data, cfg = demo_book(), demo_config()
    candidate, reference = tmp_path / "candidate.xlsx", tmp_path / "known.xlsx"
    export_workbook(process(data, cfg), candidate)
    export_workbook(process(data, cfg), reference)
    report = audit_export(data, cfg, candidate, reference)
    assert sum(f.code == "reference_value" and f.status == "PASS" for f in report.findings) == 70
    edition = load_workbook(reference)
    edition["MF · Расчёт"]["M2"] = "approved_name"
    edition.save(reference)
    changes = [f for f in audit_export(data, cfg, candidate, reference).findings
               if f.code == "reference_value" and f.status == "FAIL"]
    assert len(changes) == 1 and changes[0].expected == "approved_name"


def test_known_mark_pattern_with_explicit_category_and_type(tmp_path):
    data = demo_book()
    sheet = SheetData("known", (("EAST", "NORTH", "RL", "JOIN", "CODE", "ВИД_РАБОТ"),
                                (20, 30, -350, 1538, "N", "ГПР"), (25, 31, -350, 1538, "N", "ГПР")))
    data = replace(data, sheets=(sheet,))
    rule = NamingRule(style="case", kind_code="OBD", kind_name="Орт буро-доставочный")
    cfg = ProcessingConfig(suggest(sheet), numbering=True, first=5, naming=rule, unit="м")
    result = process(data, cfg)
    item = result.excavations[0]
    assert item.mark == "350_5_N_OBD_P"
    assert item.name == "Орт буро-доставочный 5 отм.-350м (порода)"
    out = tmp_path / "mark.xlsx"
    export_workbook(result, out)
    assert audit_export(data, cfg, out).counts["FAIL"] == 0


def test_case_mark_conflict_clears_both_members():
    data = demo_book()
    head = ("EAST", "NORTH", "RL", "JOIN", "CODE", "ВИД_РАБОТ", "PAIR_ID", "РУДНОЕ_ТЕЛО")
    rows = [
        (0, 1, -350, "A", "N", "ГПР", "PAIR", "one"),
        (1, 1, -350, "A", "N", "ГПР", "PAIR", "one"),
        (2, 1, -350, "B", "N", "НР", "PAIR", "one"),
        (3, 1, -350, "B", "N", "НР", "PAIR", "one"),
        (4, 1, -350, "C", "N", "ГПР", None, "two"),
        (5, 1, -350, "C", "N", "ГПР", None, "two"),
    ]
    sheet = SheetData("axes", (head, *rows))
    data = replace(data, sheets=(sheet,))
    cfg = ProcessingConfig(suggest(sheet), bodies=(OreBody("one", "1"), OreBody("two", "2")),
                           naming=NamingRule(style="case", kind_code="OBD"), numbering=True)
    result = process(data, cfg)
    assert all(not e.mark for e in result.excavations)
    assert result.excavations[0].related == (result.excavations[1].id,)
    assert any(i.code == "number_conflict" for i in result.issues)


def test_mapped_order_is_required_even_when_all_values_are_blank():
    data = demo_book()
    work, contour = data.sheets
    work = replace(work, rows=(work.rows[0] + ("POINT_ORDER",), *(r + (None,) for r in work.rows[1:])))
    data = replace(data, sheets=(work, contour))
    cfg = replace(demo_config(), working=suggest(work))
    result = process(data, cfg)
    assert all(e.length is None and not e.mark for e in result.excavations)
    assert sum(i.code == "order_conflict" for i in result.issues) == len(result.excavations)


@pytest.mark.skipif(not os.environ.get("MINEFLOW_REAL_XLSX"), reason="Требуется исходная книга")
@pytest.mark.parametrize("length_mode", ("XY", "XYZ"))
def test_real_case_validator(tmp_path, length_mode):
    path = Path(os.environ["MINEFLOW_REAL_XLSX"])
    source = read_workbook(path, os.environ["MINEFLOW_INPUT_KEY"])
    cfg = ProcessingConfig(*(suggest(s) for s in source.sheets), length_mode=length_mode, numbering=True,
                           classification="geometry")
    target = tmp_path / "case.xlsx"
    result = process(source, cfg)
    export_workbook(result, target, source_path=path)
    report = audit_export(source, cfg, target)
    assert report.counts["FAIL"] == 0, [f for f in report.findings if f.status == "FAIL"]
    assert report.objects == 76 and report.rows == 394 and report.outline_rows == 1153
    assert report.lengths == 74 and report.max_length_delta < 1e-10
    assert {e.group for e in result.excavations if e.contour_copy} == {"1732", "1733"}
    demo_axis = next(e for e in result.excavations if e.group == "1538")
    assert demo_axis.spatial == "Пересекает границу" and not demo_axis.mark
    assert round(demo_axis.length, 6) == 94.409991
    assert demo_axis.reference and demo_axis.display_mark == "350_5_N_OBD_P"
    assert report.counts["FAIL"] == 0
    assert any(f.code == "example_mark" and f.status == "PASS" for f in report.findings)

