from collections import defaultdict
import os
from pathlib import Path

import numpy as np
import pyvista as pv
from PySide6.QtCore import Qt, Signal
from pyvistaqt import QtInteractor
from vtkmodules.vtkRenderingCore import vtkCellPicker

from app.ui.style import BG, ERROR, ORE, PRIMARY, SUCCESS, TEXT

STEEL = "#99B2C9"
GRID = "#7E98B1"
WARNING = "#F5CE8B"


def packed_mesh(traces):
    """Encode each path as a VTK polyline, preserving its exact XYZ and owner."""
    points, lines, verts = [], [], []
    vertex_ids, line_ids = [], []
    for paths, owner in traces:
        for path in paths:
            if not path:
                continue
            offset = len(points)
            points.extend(path)
            if len(path) == 1:
                verts.extend((1, offset))
                vertex_ids.append(owner)
            else:
                lines.extend((len(path), *range(offset, offset + len(path))))
                line_ids.append(owner)
    if not points:
        return None
    mesh = pv.PolyData(np.asarray(points, dtype=np.float64),
                       lines=np.asarray(lines, dtype=np.int64) if lines else None,
                       verts=np.asarray(verts, dtype=np.int64) if verts else None)
    mesh.cell_data["mineflow_owner"] = np.array(vertex_ids + line_ids, dtype=np.int64)
    return mesh


class VtkScene(QtInteractor):
    object_picked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent=parent, auto_update=0, multi_samples=4, line_smoothing=True)
        self.set_background(BG, top="#1A293A")
        self.enable_trackball_style()
        self.enable_parallel_projection()
        self.picker = vtkCellPicker()
        self.picker.SetTolerance(0.009)
        self.index_to_owner = []
        self.meshes = {}
        self.press_pos = None
        self.grid = True
        self.labels = True
        self.focus_actors = []
        self.shapes = {}
        self.markers = {}
        self.show_axes()
        self.renderer.axes_widget.SetViewport(0.015, 0.015, 0.13, 0.16)
        self.setMinimumSize(200, 180)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_pos = event.position()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if (event.button() == Qt.MouseButton.LeftButton and self.press_pos is not None
                and (event.position() - self.press_pos).manhattanLength() < 5):
            x, y = self.iren.interactor.GetEventPosition()
            self.pick_at(x, y)

    def pick_at(self, x, y):
        if not self.picker.Pick(x, y, 0, self.renderer):
            return None
        dataset = self.picker.GetDataSet()
        cid = self.picker.GetCellId()
        owners = dataset.GetCellData().GetArray("mineflow_owner") if dataset is not None else None
        if owners is None or cid < 0:
            return None
        index = int(owners.GetValue(cid))
        if not 0 <= index < len(self.index_to_owner):
            return None
        owner = self.index_to_owner[index]
        self.object_picked.emit(owner)
        return owner

    def draw(self, objects, contours, marker_labels, problems, severe, show_relations, reset=False):
        original_camera = tuple(tuple(part) for part in self.camera_position)
        self.clear()
        self.meshes.clear()
        self.index_to_owner = []
        self.focus_actors = []
        self.shapes = {shape.id: shape for shape, _ in objects}
        self.markers = marker_labels
        bins = defaultdict(list)
        for shape, valid in contours:
            bins[("contour", ORE if valid else ERROR)].append((shape.paths, -1))
        for shape, item in objects:
            color = (ERROR if item.id in severe else WARNING if item.id in problems
                     else {"R": ORE, "P": PRIMARY}.get(item.category, STEEL))
            bins[("object", color)].append((shape.paths, len(self.index_to_owner)))
            self.index_to_owner.append(item.id)
        for (role, color), traces in bins.items():
            mesh = packed_mesh(traces)
            if mesh is not None:
                self.meshes[role, color] = mesh
                self.add_mesh(mesh, color=color, name=f"{role}-{color}", lighting=False, preference="cell",
                              line_width=2.2 if role == "object" else 1.45,
                              opacity=1.0 if role == "object" else 0.75, point_size=7,
                              render_points_as_spheres=True, pickable=role == "object", render=False,
                              reset_camera=False)
        if show_relations:
            links = set()
            for shape, item in objects:
                for target in item.related:
                    links.add(tuple(sorted((shape.id, target))))
            paths = []
            for a, b in sorted(links):
                first, second = self.shapes.get(a), self.shapes.get(b)
                if first and second and first.paths and second.paths:
                    endpoints = tuple((path[0], path[-1]) for path in (first.paths[0], second.paths[0]))
                    candidates = [(x, y) for x in endpoints[0] for y in endpoints[1]]
                    endpoints = min(candidates, key=lambda pair: sum((a - b) ** 2 for a, b in zip(*pair)))
                    paths.append((endpoints[0],) if endpoints[0] == endpoints[1] else endpoints)
            self.add_paths(paths, SUCCESS, "explicit-links", 2.2, opacity=0.85, point_size=5)
        self.draw_labels()
        self.rebuild_grid()
        if self.meshes and reset:
            self.view_isometric()
            self.fit_all(render=False)
        elif self.meshes:
            self.camera_position = original_camera
            self.reset_camera_clipping_range()
        self.render()

    def add_paths(self, paths, color, name, width, opacity=1.0, point_size=8):
        mesh = packed_mesh(((paths, -1),))
        if mesh is None:
            return None
        return self.add_mesh(mesh, name=name, color=color, lighting=False, line_width=width,
                             point_size=point_size, render_points_as_spheres=True, opacity=opacity,
                             pickable=False, render=False, reset_camera=False)

    @staticmethod
    def label_position(paths):
        path = max(paths, key=len)
        points = np.asarray(path)
        if len(points) == 1:
            return points[0]
        lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
        distance = np.cumsum(lengths)
        halfway = distance[-1] / 2
        segment = min(int(np.searchsorted(distance, halfway)), len(lengths) - 1)
        if lengths[segment] == 0:
            return points[segment]
        previous = distance[segment - 1] if segment else 0
        fraction = (halfway - previous) / lengths[segment]
        return points[segment] + fraction * (points[segment + 1] - points[segment])

    def draw_labels(self):
        self.remove_actor("numbers", render=False)
        displayed = [(self.label_position(self.shapes[k].paths), value) for k, value in self.markers.items()
                     if k in self.shapes and self.shapes[k].paths]
        if displayed and self.labels:
            font = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts" / "segoeui.ttf"
            self.add_point_labels([p for p, _ in displayed], [value for _, value in displayed],
                                  name="numbers", font_size=11, bold=False, text_color="#D8E9F7", shape=None,
                                  font_file=str(font) if font.exists() else None,
                                  point_size=0, show_points=False, always_visible=False,
                                  pickable=False, render=False, reset_camera=False)

    def rebuild_grid(self):
        self.remove_bounds_axes()
        if self.grid and self.meshes:
            axes = self.show_bounds(
                grid="back", location="outer", color=GRID, font_size=9, use_2d=True,
                use_3d_text=False, xtitle="EAST", ytitle="NORTH", ztitle="RL", fmt="%.0f",
                n_xlabels=3, n_ylabels=3, n_zlabels=4, bold=False, all_edges=False, render=False,
            )
            axes.SetScreenSize(8)
            axes.SetZAxisVisibility(True)
            for axis in range(3):
                axes.GetTitleTextProperty(axis).SetFontSize(10)
                axes.GetLabelTextProperty(axis).SetFontSize(9)
            for direction in ("X", "Y", "Z"):
                getattr(axes, f"Get{direction}AxesGridlinesProperty")().SetColor(0.19, 0.27, 0.35)
                getattr(axes, f"Get{direction}AxesLinesProperty")().SetColor(0.29, 0.39, 0.48)

    def fit_all(self, render=True):
        if not self.meshes:
            return
        self.reset_camera(render=False)
        self.camera.zoom(0.84)
        self.reset_camera_clipping_range()
        if render:
            self.render()

    def highlight(self, item_id, related=(), center=False):
        for name in self.focus_actors:
            self.remove_actor(name, render=False)
        self.focus_actors = []
        for member, color, width in ((item_id, TEXT, 5.0), *((k, SUCCESS, 4.0) for k in related)):
            shape = self.shapes.get(member)
            if shape and shape.paths:
                name = f"selection-{member}"
                self.add_paths(shape.paths, color, name, width)
                self.focus_actors.append(name)
        if center:
            shape = self.shapes.get(item_id)
            if shape and shape.paths:
                points = np.asarray([p for path in shape.paths for p in path])
                target = points.mean(axis=0)
                shift = target - np.asarray(self.camera.focal_point)
                self.camera.position = tuple(np.asarray(self.camera.position) + shift)
                self.camera.focal_point = tuple(target)
                self.reset_camera_clipping_range()
        self.render()

