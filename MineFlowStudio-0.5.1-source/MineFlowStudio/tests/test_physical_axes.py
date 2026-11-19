from collections import defaultdict
from dataclasses import replace
from hashlib import sha256
from math import cos,sin,radians
from pathlib import Path
import os

from openpyxl import load_workbook, Workbook
import pytest

from domain.models import ProcessingConfig,SheetData,WorkbookData
from services.importer import read_workbook,suggest
from services.processing import process
from services.workbook_delivery import save_delivery
from services.delivery_audit import audit_delivery

REAL=os.environ.get("MINEFLOW_REAL_XLSX")


@pytest.mark.skipif(not REAL,reason="Требуется исходная книга")
@pytest.mark.parametrize("mode",("XY","XYZ"))
@pytest.mark.parametrize("direction",("north_south","south_north"))
def test_screenshot_has_exactly_six_numbered_lines(tmp_path,mode,direction):
    path=Path(REAL)
    before=sha256(path.read_bytes()).digest()
    source=read_workbook(path,os.environ["MINEFLOW_INPUT_KEY"])
    cfg=ProcessingConfig(*(suggest(s) for s in source.sheets),numbering=True,
                         direction=direction,length_mode=mode)
    result=process(source,cfg)
    assert len(result.excavations)==76 and len(result.segments)==141
    assert sum(s.line_role=="line" for s in result.segments)==125
    assert sum(s.line_role=="transition" for s in result.segments)==14
    level=[s for s in result.segments if s.horizon=="-350"]
    pairs=({"1604","1671"},{"1605","1671"},{"1536","1606"},
           {"1537","1607"},{"1538","1608"},{"1539","1609"})
    expected=range(1,7) if direction=="north_south" else range(6,0,-1)
    for number,joins in zip(expected,pairs):
        members=[s for s in level if s.number==number]
        assert {s.group for s in members}==joins
        assert len({s.number_group for s in members})==1
        assert all(s.line_role=="line" for s in members)
    assert {s.number for s in level if s.number is not None}==set(range(1,7))
    connectors=[s for s in level if s.line_role=="transition"]
    assert len(connectors)==2 and all(s.number is None for s in connectors)
    assert {s.numbers for s in connectors}=={(1,2),(5,6)}
    by_axis={a.id:a for a in result.excavations}
    assert len(by_axis["X33"].numbers)==2 and by_axis["X33"].number is None
    for axis in result.excavations:
        pieces=[s for s in result.segments if s.axis_id==axis.id]
        if axis.length is not None and not axis.contour_copy:
            assert sum(s.length or 0 for s in pieces)==pytest.approx(axis.length,abs=1e-8)
    target=tmp_path/"lines.xlsx"
    save_delivery(result,target)
    report=audit_delivery(source,cfg,target)
    assert not report.counts["FAIL"],[f for f in report.findings if f.status=="FAIL"]
    assert report.counts["UNVERIFIED"]==27
    assert sha256(path.read_bytes()).digest()==before
    workbook=load_workbook(target)
    headers={c.value:i for i,c in enumerate(workbook["Участки"][1],1)}
    row=next(i for i in range(2,workbook["Участки"].max_row+1)
             if workbook["Участки"].cell(i,headers["Роль участка"]).value=="Переход")
    workbook["Участки"].cell(row,headers["Номер по настройкам"]).value=7
    workbook["Участки"].cell(row,headers["Роль участка"]).value="Линия"
    workbook.save(target)
    failures={f.code for f in audit_delivery(source,cfg,target).findings if f.status=="FAIL"}
    assert {"number_by_rule","line_role"}<=failures


def simple_book(rotation=0,gap=0,z2=-350):
    head=("EAST","NORTH","RL","JOIN","РУДНОЕ_ТЕЛО","ВИД_РАБОТ","ГОРИЗОНТ")
    angle=radians(rotation)
    def row(x,y,z,join,cat):
        return (x*cos(angle)-y*sin(angle),x*sin(angle)+y*cos(angle),z,join,"A",cat,-350)
    records=[head]
    # Distinct JOINs on each straight line; an overlapping source portion;
    # a connector touching both lines, which must not merge their numbers.
    for join,cat,points,z in (
        ("P1","ГПР",((0,10),(5,10)),-350),
        ("R1","НР",((5+gap,10),(15,10)),z2),
        ("P2","ГПР",((0,0),(5,0)),-350),
        ("R2","НР",((5,0),(15,0)),-350),
        ("overlap","ГПР",((9,0),(12,0)),-350),
        ("curve","ГПР",((10,10),(13,7),(12,3),(10,0)),-350),
    ):
        records.extend(row(x,y,z,join,cat) for x,y in points)
    data=WorkbookData("Test",(SheetData("axes",tuple(records)),))
    cfg=ProcessingConfig(suggest(data.sheets[0]),numbering=True,split_rule="whole",
                         direction="north_south",line_azimuth=(90-rotation)%180)
    return data,cfg


@pytest.mark.parametrize("rotation",(0,27,90))
def test_parallel_lines_are_joined_across_join_but_connectors_are_not(tmp_path,rotation):
    data,cfg=simple_book(rotation)
    raw=tmp_path/"input.xlsx"
    workbook=Workbook()
    workbook.active.title="axes"
    for row in data.sheets[0].rows:
        workbook.active.append(row)
    workbook.save(raw)
    workbook.close()
    data=read_workbook(raw)
    cfg=replace(cfg,working=suggest(data.sheets[0]))
    result=process(data,cfg)
    axes={a.group:a for a in result.excavations}
    assert axes["P1"].number==axes["R1"].number
    assert axes["P2"].number==axes["R2"].number==axes["overlap"].number
    assert axes["P1"].number!=axes["P2"].number
    assert axes["curve"].number is None
    assert all(s.number is None for s in result.segments if s.group=="curve")
    target=tmp_path/"geometry.xlsx"
    save_delivery(result,target)
    report=audit_delivery(data,cfg,target)
    assert report.counts["FAIL"]==0,[f for f in report.findings if f.status=="FAIL"]


@pytest.mark.parametrize("gap,z2",((.02,-350),(0,-349)))
def test_gaps_and_another_height_do_not_merge(gap,z2):
    data,cfg=simple_book(gap=gap,z2=z2)
    result=process(data,cfg)
    axes={a.group:a for a in result.excavations}
    assert axes["P1"].number!=axes["R1"].number


@pytest.mark.skipif(not REAL,reason="Требуется исходная книга")
def test_line_numbers_are_independent_of_material_splitting_and_links(tmp_path):
    source=read_workbook(Path(REAL),os.environ["MINEFLOW_INPUT_KEY"])
    cfg=ProcessingConfig(*(suggest(s) for s in source.sheets),numbering=True,direction="north_south")
    baseline=process(source,cfg)
    reference={a.id:a.numbers for a in baseline.excavations}
    for splitting,links in (("whole","none"),("contour","none"),("contour","explicit")):
        current=replace(cfg,split_rule=splitting,link_rule=links)
        result=process(source,current)
        assert {a.id:a.numbers for a in result.excavations}==reference
        target=tmp_path/f"{splitting}-{links}.xlsx"
        save_delivery(result,target)
        report=audit_delivery(source,current,target)
        assert report.counts["FAIL"]==0,[f for f in report.findings if f.status=="FAIL"]
    continuous=process(source,replace(cfg,numbering_scope="body",direction="top_bottom"))
    units={s.number_group:s.number for s in continuous.segments if s.number is not None}
    assert sorted(units.values())==list(range(1,37))
    top={s.number for s in continuous.segments if s.horizon=="-350" and s.number is not None}
    assert top==set(range(1,7))

