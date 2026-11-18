from dataclasses import replace
import os
from pathlib import Path

import numpy as np
import pytest

from app.ui.vtk_scene import packed_mesh
from domain.models import ProcessingConfig
from fixtures.demo import demo_book, demo_config
from services.importer import read_workbook, suggest
from services.processing import process
from services.spatial_model import build_spatial_model


def test_vtk_polydata_preserves_double_precision_and_owner():
    first = ((48907.73733, 49255.49533, -350), (48813.32738, 49255.58324, -350))
    singleton = ((48765.35678, 49356.45678, -500),)
    mesh = packed_mesh((( (first,), 25), ((singleton,), 37)))
    assert mesh.points.dtype == np.float64
    np.testing.assert_array_equal(mesh.points, np.asarray((*first, *singleton)))
    np.testing.assert_array_equal(mesh.cell_data["mineflow_owner"], (37, 25))
    assert mesh.n_lines == 1 and mesh.n_verts == 1


def test_missing_rl_breaks_axis_instead_of_interpolating():
    data = demo_book()
    work, contour = data.sheets
    columns = list(work.rows[0]) + ["ГОРИЗОНТ"]
    rows = [tuple(columns)]
    for row in work.rows[1:]:
        altered = list(row) + [row[2]]
        if row[3] == "D" and row[0] == 23:
            altered[2] = None
        rows.append(tuple(altered))
    work = replace(work, rows=tuple(rows))
    source = replace(data, sheets=(work, contour))
    cfg = replace(demo_config(), working=suggest(work))
    result = process(source, cfg)
    shape = next(shape for shape, item in zip(build_spatial_model(result)[0], result.excavations)
                 if item.group == "D")
    assert shape.unplaced == 1 and len(shape.paths) == 2 and all(len(p) == 1 for p in shape.paths)


@pytest.mark.skipif(not os.environ.get("MINEFLOW_REAL_XLSX"), reason="Требуется исходная книга")
def test_real_3d_matches_every_raw_vertex():
    path = Path(os.environ["MINEFLOW_REAL_XLSX"])
    source = read_workbook(path, os.environ["MINEFLOW_INPUT_KEY"])
    cfg = ProcessingConfig(*(suggest(s) for s in source.sheets))
    result = process(source, cfg)
    objects, outlines = build_spatial_model(result)
    all_shapes, all_items = objects + outlines, result.excavations + result.contours
    expected = [tuple(source.sheet(ref.sheet).values(ref.row)[:3]) for item in all_items for ref in item.refs]
    mesh = packed_mesh((shape.paths, i) for i, shape in enumerate(all_shapes))
    assert len(expected) == 1547 and len(objects) == 76 and len(outlines) == 7
    np.testing.assert_array_equal(mesh.points, np.asarray(expected, dtype=np.float64))
    assert set(mesh.points[:, 2]) == {-350, -375, -400, -425, -450, -475, -500}
    trial = process(source, replace(cfg, numbering=True, classification="geometry"))
    assert build_spatial_model(trial) == (objects, outlines)

