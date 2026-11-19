from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFormLayout, QVBoxLayout, QWidget
import pytest

from app.ui.map_view import MapView
from app.ui.rules import RulePanel
from app.ui.style import STYLES
from app.ui.widgets import PropertyValue, label, property_form
from domain.models import Excavation, Point3D, ProcessingConfig, RowRef
from fixtures.demo import demo_config


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")
    application.setStyleSheet(STYLES)
    return application


def test_common_axis_badges_are_separate_after_zoom_pan_resize(app):
    objects = []
    for i in range(18):
        for ordinal, (start, end, cat) in enumerate(((-10,0,"P"),(0,10,"R"),(10,20,"P")),1):
            objects.append(Excavation(
                f"X{i}.{ordinal}",str(i),"-350","body",(RowRef("axes",i*2+2),),
                ((Point3D(start,i*0.05,-350),Point3D(end,i*0.05,-350)),),
                category=cat,number=i+1,axis_id=f"X{i}",ordinal=ordinal))
    view = MapView()
    view.resize(720,480)
    view.show()
    view.populate(objects,[],set())
    app.processEvents()
    assert len(view.labels) == 18
    for action in (lambda:None,lambda:view.zoom(1.8),lambda:view.resize(500,360),
                   lambda:view.centerOn(0,0),view.fit):
        action()
        app.processEvents()
        badges = view.label_layout()
        assert len(badges) == 18
        assert len({view.lines[key][1].axis_id for key,_,_,_ in badges}) == len(badges)
        for i, (key,text,rect,_) in enumerate(badges):
            assert all(not rect.intersects(other[2]) for other in badges[i+1:])
            assert view.object_at(rect.center().toPoint()) == key
            assert text == str(view.lines[key][1].number)
    view.set_layers(numbers=False)
    assert not view.label_layout()
    view.set_layers(numbers=True)
    assert len(view.label_layout()) == 18
    view.close()


def test_long_plain_property_values_wrap_without_losing_characters(app):
    panel = QWidget()
    panel.setFixedWidth(195)
    layout = QFormLayout(panel)
    property_form(layout)
    value = PropertyValue()
    text = "НовоИТишное2026_" * 20
    layout.addRow(label("Обозначение","muted"),value)
    value.setText(text)
    panel.show()
    app.processEvents()
    document = value.document()
    block = document.firstBlock().layout()
    assert value.text() == text and value.toPlainText() == text
    assert block.lineCount() > 10
    last = block.lineAt(block.lineCount()-1)
    assert last.textStart()+last.textLength() == len(text)
    assert value.height() >= document.documentLayout().documentSize().height()
    assert value.horizontalScrollBar().maximum() == 0
    panel.close()


def test_rule_panel_loads_both_scopes_and_cardinal_directions(app):
    panel = RulePanel()
    cfg = demo_config()
    for scope in ("body","horizon"):
        for direction in ("north_south","south_north","west_east","east_west","top_bottom","bottom_top","custom"):
            settings = replace(cfg,numbering_scope=scope,direction=direction)
            for unit in ("axis","source","linked"):
                unit_settings=replace(settings,numbering_unit=unit)
                panel.load_config(unit_settings)
                assert panel.config(cfg.working,cfg.contour) == unit_settings
            assert panel.order.isEnabled() == (direction == "custom")
    panel.close()



def test_linked_axes_share_one_badge_in_2d_and_3d(app):
    from app.ui.spatial_page import SpatialPage
    from fixtures.demo import demo_book
    from services.processing import process

    cfg=replace(demo_config(),split_rule="whole",link_rule="explicit",numbering_unit="linked")
    result=process(demo_book(),cfg)
    edge=result.links[0]
    pair=[s for s in result.segments if s.id in (edge.rock,edge.ore)]
    assert pair[0].axis_id != pair[1].axis_id and pair[0].number == pair[1].number
    view=MapView()
    view.resize(600,400)
    view.show()
    view.populate(pair,[],set())
    app.processEvents()
    assert len(view.labels)==1 and len(view.label_layout())==1
    for part in pair:
        view.highlight(part.id)
        app.processEvents()
        assert len(view.label_layout())==1
        assert view.label_layout()[0][1]==str(part.number)
    view.close()
    page=SpatialPage()
    page.resize(1100,700)
    page.show()
    page.set_result(replace(result,excavations=tuple(pair)))
    app.processEvents()
    assert len(page.scene.markers)==1 and next(iter(page.scene.markers.values()))==str(pair[0].number)
    for part in pair:
        page.select(part.id)
        assert page.properties["Номер"].text()==str(part.number)
    page.scene.close()
    page.close()


@pytest.mark.skipif(not __import__("os").environ.get("MINEFLOW_REAL_XLSX"),reason="Требуется исходная книга")
def test_screenshot_six_lines_are_clickable_on_both_sides(app):
    import os
    from pathlib import Path
    from PySide6.QtTest import QTest
    from services.importer import read_workbook,suggest
    from services.processing import process

    data=read_workbook(Path(os.environ["MINEFLOW_REAL_XLSX"]),os.environ["MINEFLOW_INPUT_KEY"])
    cfg=ProcessingConfig(*(suggest(s) for s in data.sheets),numbering=True,direction="north_south")
    result=process(data,cfg)
    pieces=[s for s in result.segments if s.horizon=="-350"]
    view=MapView()
    view.resize(900,600)
    view.show()
    view.populate(pieces,[c for c in result.contours if c.horizon=="-350"],set())
    while view.pending:
        app.processEvents()
    app.processEvents()
    labels=view.label_layout()
    assert [text for _,text,rect,_ in sorted(labels,key=lambda p:p[2].center().y())]==list("123456")
    selected=[]
    view.picked.connect(selected.append)
    objects={s.id:s for s in pieces}
    for number in range(1,7):
        for material in ("P","R"):
            target=max((s for s in pieces if s.number==number and s.category==material),key=lambda s:s.length)
            position=view.mapFromScene(view.lines[target.id][0].path().pointAtPercent(.5))
            QTest.mouseClick(view.viewport(),Qt.MouseButton.LeftButton,pos=position)
            app.processEvents()
            assert selected and objects[selected[-1]].number==number
            assert f">{number}<" in view.tooltip_text(objects[selected[-1]])
    view.close()
