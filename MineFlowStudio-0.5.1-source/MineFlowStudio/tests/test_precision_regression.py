from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from xml.etree import ElementTree as ET
import os

from openpyxl import Workbook,load_workbook
import pytest

from domain.models import ColumnMap,ProcessingConfig,SheetData,WorkbookData
from services.importer import read_workbook,suggest
from services.processing import process
from services.workbook_delivery import save_delivery
from services.delivery_audit import audit_delivery
from services.publication import publish
from services.validation import horizon_key

NEW=os.environ.get("MINEFLOW_NEW_XLSX")
NS={"s":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def rewrite_numbers(path,member,replacements):
    with ZipFile(path) as archive:
        files={i.filename:(i,archive.read(i.filename)) for i in archive.infolist()}
    info,data=files[member]
    root=ET.fromstring(data)
    for cell in root.findall(".//s:c",NS):
        if cell.get("r") in replacements:
            cell.find("s:v",NS).text=replacements[cell.get("r")]
    files[member]=info,ET.tostring(root,encoding="utf-8",xml_declaration=True)
    with ZipFile(path,"w",ZIP_DEFLATED) as archive:
        for info,data in files.values():
            archive.writestr(info,data)


@pytest.mark.parametrize("mode",("XY","XYZ"))
def test_full_float_precision_is_preserved_in_source_and_vertices(tmp_path,mode):
    raw=tmp_path/"precision.xlsx"
    wb=Workbook()
    ws=wb.active
    ws.title="Axes"
    ws.append(("EAST","NORTH","RL","JOIN","Precise number","Zero float"))
    ws.append((0,0,0,"A",0,0))
    ws.append((1,1,0,"A",1,0))
    ws["A2"].number_format="0.000000000000000"
    wb.save(raw)
    wb.close()
    exact={
        "A2":"51657.870200763355","B2":"50834.460205082054","C2":"-374.99999999988364",
        "E2":"1.0000000000000002","F2":"0.0",
        "A3":"51668.15435281226","B3":"50834.460205082054","C3":"-374.9999999998836",
        "E3":"0.000000000000000173",
    }
    rewrite_numbers(raw,"xl/worksheets/sheet1.xml",exact)
    source=read_workbook(raw)
    cfg=ProcessingConfig(suggest(source.sheets[0]),numbering=True,split_rule="whole",length_mode=mode)
    result=process(source,cfg)
    assert len(result.excavations)==1 and result.excavations[0].horizon=="-375"
    assert result.excavations[0].parts[0][0].rl==float(exact["C2"])
    out=tmp_path/"precise-result.xlsx"
    save_delivery(result,out)
    assert read_workbook(out).sheets==source.sheets
    report=audit_delivery(source,cfg,out)
    assert report.counts["FAIL"]==0,[f for f in report.findings if f.status=="FAIL"]
    wb=load_workbook(out)
    assert wb["Axes"]["A2"].value==float(exact["A2"]) and wb["Axes"]["A2"].data_type=="n"
    assert wb["Axes"]["E2"].value==float(exact["E2"]) and wb["Axes"]["F2"].value==0.0
    assert wb["Axes"]["A2"].number_format=="0.000000000000000"
    point_values=list(wb["Точки участков"].values)[1:]
    assert point_values[0][3:6]==result.excavations[0].parts[0][0].xy+(float(exact["C2"]),)
    wb.close()
    # A true coordinate edit still fails the strict audit; no tolerance was
    # added to the source-value comparison to hide precision regressions.
    changed=str(Decimal(exact["A2"])+Decimal("0.000001"))
    rewrite_numbers(out,"xl/worksheets/sheet1.xml",{"A2":changed})
    codes={f.code for f in audit_delivery(source,cfg,out).findings if f.status=="FAIL"}
    assert {"source_cells","source_cell"}<=codes


def test_rl_noise_changes_only_the_group_key():
    values=(-375,-374.9999999998836,-374.99999999988364)
    assert {horizon_key(x,elevation=True) for x in values}=={"-375"}
    assert horizon_key(-375.0001,elevation=True)=="-375.0001"
    assert horizon_key(-375.25,elevation=True)=="-375.25"
    assert horizon_key("00375",elevation=False)=="00375"
    head=("EAST","NORTH","RL","JOIN")
    sheet=SheetData("Axes",(head,(0,0,values[1],"A"),(3,4,values[2],"A")))
    result=process(WorkbookData("Noise",(sheet,)),ProcessingConfig(suggest(sheet),length_mode="XYZ"))
    assert len(result.excavations)==1
    assert [p.rl for p in result.excavations[0].parts[0]]==list(values[1:])
    assert result.excavations[0].length==5


def test_explicit_named_horizons_are_not_rewritten():
    head=("EAST","NORTH","RL","JOIN","ГОРИЗОНТ")
    sheet=SheetData("Axes",(head,(0,0,-374.99999999,"A","00375"),(1,0,-375,"A","00375")))
    result=process(WorkbookData("Named",(sheet,)),ProcessingConfig(suggest(sheet)))
    assert len(result.excavations)==1 and result.excavations[0].horizon=="00375"


@pytest.mark.skipif(not NEW,reason="Требуется новая тестовая книга")
@pytest.mark.parametrize("mode",("XY","XYZ"))
def test_new_customer_book_has_no_false_failures(tmp_path,mode):
    path=Path(NEW)
    before=sha256(path.read_bytes()).digest()
    source=read_workbook(path,os.environ["MINEFLOW_INPUT_KEY"])
    cfg=ProcessingConfig(*(suggest(s) for s in source.sheets),numbering=True,
                         direction="north_south",length_mode=mode)
    result=process(source,cfg)
    assert len(result.excavations)==24 and sum(len(e.refs) for e in result.excavations)==83
    assert len(result.contours)==2 and all(c.valid for c in result.contours)
    assert len(result.segments)==28
    assert {e.horizon for e in result.excavations}=={"-350","-375"}
    assert all(e.length is not None for e in result.excavations)
    assert not result.issues
    for level in ("-350","-375"):
        assert {s.number for s in result.segments if s.horizon==level and s.number is not None}==set(range(1,7))
    target=tmp_path/"Test-Result.xlsx"
    report,saved=publish(result,target,path,None)
    assert saved and report.counts["FAIL"]==0,[f for f in report.findings if f.status=="FAIL"]
    assert report.counts["UNVERIFIED"]==2
    assert read_workbook(target).sheets==source.sheets
    assert sha256(path.read_bytes()).digest()==before


def test_real_invalid_coordinates_still_report_errors():
    sheet=SheetData("Axes",(("EAST","NORTH","RL","JOIN"),(0,0,-375,"A"),("bad",1,-375,"A")))
    result=process(WorkbookData("Bad",(sheet,)),ProcessingConfig(suggest(sheet)))
    assert any(i.code=="coordinates" and i.severity=="Ошибка" for i in result.issues)
    assert result.excavations[0].length is None



def test_numpy_float_subclasses_remain_valid_numeric_cells(tmp_path):
    import numpy as np
    from services.exporter import write_values
    path=tmp_path/"numpy.xlsx"
    wb=Workbook()
    values=(np.float64(51657.870200763355),np.float64(0.0))
    write_values(wb.active,1,values)
    wb.save(path)
    wb.close()
    wb=load_workbook(path)
    assert tuple(c.value for c in wb.active[1])==tuple(map(float,values))
    assert all(c.data_type=="n" for c in wb.active[1])
    wb.close()
