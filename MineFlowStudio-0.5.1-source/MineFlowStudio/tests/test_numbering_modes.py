from dataclasses import replace
from collections import defaultdict

from openpyxl import load_workbook
import pytest

from domain.models import Excavation, Point3D, ProcessingConfig, RowRef, SheetData, WorkbookData
from domain.status import PRELIMINARY
from fixtures.demo import demo_book
from services.audit_geometry import audit_groups
from services.audit_numbering import audited_axis_assignment
from services.delivery_audit import audit_delivery
from services.importer import suggest
from services.numbering import assign_axis_numbers
from services.processing import process
from services.result_audit import audit_export
from services.exporter import export_workbook
from services.validation import IssueLog
from services.workbook_delivery import save_delivery


@pytest.mark.parametrize("split", ("whole","contour"))
@pytest.mark.parametrize("scope", ("horizon","body"))
@pytest.mark.parametrize("direction", ("north_south","south_north","top_bottom"))
def test_two_axes_can_share_one_number_only_in_linked_mode(tmp_path, scope, direction, split):
    source = demo_book()
    cfg = ProcessingConfig(*(suggest(s) for s in source.sheets), numbering=True,
                           split_rule=split, link_rule="explicit", numbering_unit="linked",
                           numbering_scope=scope, direction=direction, first=3)
    linked = process(source,cfg)
    separate = process(source,replace(cfg,numbering_unit="axis"))
    assert [e.parts for e in linked.excavations] == [e.parts for e in separate.excavations]
    assert linked.links == separate.links
    by_id = {e.id:e for e in linked.segments}
    independent = {e.id:e for e in separate.segments}
    for edge in linked.links:
        p,r = by_id[edge.rock],by_id[edge.ore]
        assert p.axis_id != r.axis_id
        assert p.number == r.number
        assert p.number_group == r.number_group
        assert independent[p.id].number != independent[r.id].number
    owners={e.id:e for e in linked.excavations}
    assert all(e.number == owners[e.axis_id].number for e in linked.segments)
    scopes=defaultdict(set)
    for e in linked.excavations:
        if e.number is not None:
            scopes[e.body,e.horizon if scope=="horizon" else ""].add(e.number)
    assert all(sorted(ns)==list(range(3,3+len(ns))) for ns in scopes.values())
    target=tmp_path/"working.xlsx"
    save_delivery(linked,target)
    report=audit_delivery(source,cfg,target)
    assert report.counts["FAIL"]==0,[f for f in report.findings if f.status=="FAIL"]
    wb=load_workbook(target)
    assert {r[20] for r in list(wb["Участки"].values)[1:]} == {PRELIMINARY}
    assert {r[5] for r in list(wb["Связи участков"].values)[1:]} == {PRELIMINARY}
    wb.close()
    legacy=tmp_path/"technical.xlsx"
    export_workbook(linked,legacy)
    assert audit_export(source,cfg,legacy).counts["FAIL"]==0


def test_without_links_both_modes_number_axes_identically():
    source=demo_book()
    cfg=ProcessingConfig(*(suggest(s) for s in source.sheets),numbering=True,
                         split_rule="contour",link_rule="none",numbering_unit="linked")
    one=process(source,cfg)
    two=process(source,replace(cfg,numbering_unit="axis"))
    assert [(e.id,e.number) for e in one.excavations] == [(e.id,e.number) for e in two.excavations]
    assert all(len({s.number for s in one.segments if s.axis_id==a.id})==1
               for a in one.excavations if not a.contour_copy)


def test_multiple_axis_partners_are_not_automatically_merged():
    head=("EAST","NORTH","RL","JOIN","РУДНОЕ_ТЕЛО")
    rows=[head]
    for i in range(3):
        rows.extend(((i,1,-350,str(i),"A"),(i+1,1,-350,str(i),"A")))
    source=WorkbookData("Test",(SheetData("axes",tuple(rows)),))
    cfg=ProcessingConfig(suggest(source.sheets[0]),numbering=True,numbering_unit="linked",
                         split_rule="whole",link_rule="continuity")
    axes=list(process(source,cfg).excavations)
    parts=[]
    for i,(owner,category) in enumerate(((axes[0],"P"),(axes[0],"P"),(axes[1],"R"),(axes[2],"R"))):
        parts.append(Excavation(f"S{i}",owner.group,owner.horizon,owner.body,owner.refs,owner.parts,
                                axis_id=owner.id,category=category,length=1))
    parts[0].related,parts[2].related=("S2",),("S0",)
    parts[1].related,parts[3].related=("S3",),("S1",)
    log=IssueLog()
    assign_axis_numbers(axes,parts,cfg,log)
    assert len({e.number for e in axes})==3
    assert len([i for i in log.items if i.code=="numbering_group"])==3
    audited=audit_groups(source.sheets[0],cfg.working,cfg)
    links=((axes[0].id,axes[1].id),(axes[0].id,axes[2].id))
    numbers,roots,blocked=audited_axis_assignment(audited,set(),cfg,links)
    assert blocked=={e.id for e in axes}
    assert all(numbers[e.id]==e.number and roots[e.id]==e.id for e in axes)

