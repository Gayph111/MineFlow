from dataclasses import replace

import numpy as np
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QHelpEvent, QImage
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QCheckBox, QToolTip
import pytest

from app.ui.map_view import MapView
from app.ui.style import CHECKMARK, PARTIAL_CHECK, STYLES
from app.ui.vtk_scene import VtkScene
from domain.models import Excavation, Point3D, RowRef


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")
    application.setStyleSheet(STYLES)
    return application


def excavation(number=None):
    return Excavation(
        "X2", "1538", "-350", "Test",
        (RowRef("axes", 2), RowRef("axes", 3)),
        ((Point3D(0, 0, -350), Point3D(100, 0, -350)),),
        number=number,
    )


def test_hover_uses_join_and_assigned_number():
    item = excavation()
    unassigned = MapView.tooltip_text(item)
    assert "JOIN" in unassigned and "1538" in unassigned and "Не присвоен" in unassigned
    assert "Порядковый номер" in unassigned
    assigned = MapView.tooltip_text(replace(item, number=7, group="<script>"))
    assert "&lt;script&gt;" in assigned and "<script>" not in assigned
    assert ">7<" in assigned and "Не присвоен" not in assigned


def test_2d_hover_lifecycle_and_hidden_layers(app):
    view = MapView()
    view.resize(640, 400)
    view.show()
    view.populate([excavation(7)], [], set())
    app.processEvents()
    middle = view.mapFromScene(view.to_scene(50, 0))
    assert view.object_at(middle) == "X2"
    help_event = QHelpEvent(QEvent.Type.ToolTip, middle, view.viewport().mapToGlobal(middle))
    QApplication.sendEvent(view.viewport(), help_event)
    app.processEvents()
    assert view.hover_id == "X2" and "1538" in QToolTip.text() and ">7<" in QToolTip.text()
    assert not view.current
    QApplication.sendEvent(view.viewport(), QEvent(QEvent.Type.Leave))
    assert view.hover_id == "" and not view.hover_timer.isActive()
    view.set_layers(objects=False)
    assert view.object_at(middle) == ""
    QApplication.sendEvent(view.viewport(), help_event)
    assert view.hover_id == ""
    view.set_layers(objects=True)
    view.pick_start = True
    QApplication.sendEvent(view.viewport(), help_event)
    assert view.hover_id == ""
    view.pick_start = False
    view.hover_id, view.hover_position = "X2", middle
    view.hover_timer.start()
    view.clear_map()
    assert not view.hover_timer.isActive() and not view.hover_id
    view.close()


def test_checkbox_has_contrasting_checked_and_unchecked_states(app):
    assert QSvgRenderer(CHECKMARK).isValid() and QSvgRenderer(PARTIAL_CHECK).isValid()
    control = QCheckBox("Нумерация")
    control.setFixedSize(210, 36)
    control.show()
    app.processEvents()
    images = []
    for checked in (False, True):
        control.setChecked(checked)
        app.processEvents()
        images.append(control.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888))
    left, right = images
    changed = sum(left.pixel(x, y) != right.pixel(x, y) for x in range(24) for y in range(36))
    assert changed > 150
    control.close()


def test_3d_label_anchor_is_midway_along_path():
    path = (((0.0, 0.0, 0.0), (8.0, 0.0, 0.0), (8.0, 2.0, 0.0)),)
    np.testing.assert_array_equal(VtkScene.label_position(path), (5.0, 0.0, 0.0))
    np.testing.assert_array_equal(VtkScene.label_position((((1.0, 2.0, 3.0),),)), (1.0, 2.0, 3.0))
    np.testing.assert_array_equal(
        VtkScene.label_position((((1.0, 2.0, 3.0), (1.0, 2.0, 3.0)),)), (1.0, 2.0, 3.0)
    )


def test_filtered_3d_scene_uses_numbers_and_visible_grid(app):
    from app.ui.spatial_page import SpatialPage
    from fixtures.demo import demo_book, demo_config
    from services.processing import process

    result = process(demo_book(), demo_config())
    page = SpatialPage()
    page.resize(1100, 700)
    page.show()
    app.processEvents()
    page.set_result(result)
    assert page.scene.markers
    assert all(label.isdecimal() for label in page.scene.markers.values())
    axes = page.scene.renderer.cube_axes_actor
    assert axes.GetZAxisVisibility()
    assert axes.GetXAxesGridlinesProperty().GetOpacity() == 1
    page.query.setText(result.excavations[0].id)
    assert page.scene.markers and all(label.isdecimal() for label in page.scene.markers.values())
    page.scene.close()
    page.close()
