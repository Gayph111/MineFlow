from html import escape
from math import ceil, floor, log10
from time import perf_counter

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QBrush
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView, QToolTip

from app.ui.style import BG, ERROR, MUTED, ORE, PRIMARY, SUCCESS, TEXT

GRID = QColor("#243241")
CONTOUR = ORE
GRAPH_COLORS = {None: "#8BA3B8", "P": PRIMARY, "R": ORE}


class MapView(QGraphicsView):
    picked = Signal(str)
    cursor_at = Signal(float, float)
    start_picked = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor(BG))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.origin = (0.0, 0.0)
        self.bounds = QRectF(-100, -80, 200, 160)
        self.lines = {}
        self.outlines = []
        self.labels = []
        self.current = ""
        self.linked = set()
        self.press_pos = QPoint()
        self.pick_start = False
        self.layers = {"contours": True, "objects": True, "numbers": True, "issues": True}
        self.problem = set()
        self.start = None
        self.start_items = []
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.timeout.connect(self.draw_batch)
        self.pending = None
        self.hover_id = ""
        self.hover_position = QPoint()
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.setInterval(180)
        self.hover_timer.timeout.connect(self.show_hover)

    def clear_map(self):
        self.hide_hover()
        self.render_timer.stop()
        self.pending = None
        self.setUpdatesEnabled(True)
        self.scene().clear()
        self.lines = {}
        self.outlines = []
        self.labels = []
        self.start_items = []
        self.current = ""
        self.linked = set()

    def populate(self, objects, contours, problem, start=None):
        self.clear_map()
        self.problem = problem
        self.start = start
        initial = next((part[0] for shape in (*contours, *objects) for part in shape.parts if part), None)
        if initial:
            self.origin = (initial.east, initial.north)
        self.pending = self.add_shapes(objects, contours)
        self.setUpdatesEnabled(False)
        self.draw_batch()

    def draw_batch(self):
        deadline = perf_counter() + 0.012
        while perf_counter() < deadline:
            try:
                next(self.pending)
            except StopIteration:
                self.pending = None
                self.finish_map()
                return
        self.render_timer.start(1)

    def add_shapes(self, objects, contours):
        for outline in contours:
            color = QColor(CONTOUR if outline.valid else ERROR)
            path = self.make_path(outline.parts)
            pen = self.pen(color, 1.7, dashed=not outline.valid)
            fill = QColor(color)
            fill.setAlpha(20)
            item = self.scene().addPath(path, pen, QBrush(fill) if outline.valid else QBrush())
            item.setZValue(-1)
            item.setToolTip(f"Контур {outline.group} • {outline.horizon}")
            self.outlines.append(item)
            item.setVisible(self.layers["contours"])
            yield
        for obj in objects:
            if not obj.parts:
                continue
            path = self.make_path(obj.parts)
            item = self.scene().addPath(path, self.pen(QColor(GRAPH_COLORS[obj.category]), 2.1))
            item.setData(0, obj.id)
            item.setToolTip(self.tooltip_text(obj))
            self.lines[obj.id] = item, obj
            self.restyle(obj.id)
            item.setVisible(self.layers["objects"])
            if obj.display_number is not None:
                p = obj.anchor
                marker = self.scene().addSimpleText(f"{obj.display_number}" + ("*" if obj.reference else ""))
                marker.setBrush(QColor(TEXT))
                marker.setPos(self.to_scene(p.east, p.north))
                marker.setZValue(3)
                marker.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                marker.setData(0, obj.id)
                marker.setToolTip(self.tooltip_text(obj))
                marker.setVisible(self.layers["numbers"] and self.layers["objects"])
                self.labels.append(marker)
            yield

    def finish_map(self):
        self.bounds = self.scene().itemsBoundingRect()
        if self.bounds.isEmpty():
            self.bounds = QRectF(-100, -80, 200, 160)
        pad = max(self.bounds.width(), self.bounds.height(), 20) * 0.10
        self.bounds.adjust(-pad, -pad, pad, pad)
        self.setSceneRect(self.bounds.adjusted(-2 * pad, -2 * pad, 2 * pad, 2 * pad))
        self.set_start(self.start)
        self.fit()
        self.setUpdatesEnabled(True)

    def set_start(self, start):
        for item in self.start_items:
            self.scene().removeItem(item)
        self.start_items = []
        self.start = start
        if start is None:
            return
        pos = self.to_scene(*start)
        marker = self.scene().addSimpleText("⊕ Старт")
        marker.setPos(pos)
        marker.setBrush(QColor(SUCCESS))
        marker.setZValue(4)
        marker.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self.start_items.append(marker)

    def make_path(self, parts):
        path = QPainterPath()
        for part in parts:
            if len(part) == 1:
                pt = self.to_scene(*part[0].xy)
                path.addEllipse(pt, 0.8, 0.8)
                continue
            path.moveTo(self.to_scene(*part[0].xy))
            for point in part[1:]:
                path.lineTo(self.to_scene(*point.xy))
        return path

    @staticmethod
    def pen(color, width, dashed=False):
        p = QPen(color, width)
        p.setCosmetic(True)
        p.setCapStyle(Qt.PenCapStyle.RoundCap)
        if dashed:
            p.setStyle(Qt.PenStyle.DashLine)
        return p

    def set_layers(self, **layers):
        self.hide_hover()
        self.layers.update(layers)
        for item in self.outlines:
            item.setVisible(self.layers["contours"])
        for item, obj in self.lines.values():
            item.setVisible(self.layers["objects"])
            self.restyle(obj.id)
        for marker in self.labels:
            marker.setVisible(self.layers["numbers"] and self.layers["objects"])

    def restyle(self, obj_id):
        if obj_id not in self.lines:
            return
        item, obj = self.lines[obj_id]
        problem = obj_id in self.problem and self.layers["issues"]
        current = obj_id == self.current
        connected = obj_id in self.linked
        color = TEXT if current else SUCCESS if connected else ERROR if problem else GRAPH_COLORS[obj.category]
        item.setPen(self.pen(QColor(color), 3.6 if current or connected else 2.0, problem or obj.contour_copy))
        item.setZValue(3 if current else 2 if connected else 1)

    def highlight(self, obj_id, center=False, related=()):
        previous = {self.current, *self.linked}
        self.current, self.linked = obj_id, set(related)
        for key in previous | self.linked | {obj_id}:
            self.restyle(key)
        if center and obj_id in self.lines and self.pending is None:
            self.centerOn(self.lines[obj_id][0])

    def fit(self):
        self.fitInView(self.bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, factor):
        self.hide_hover()
        effective = abs(self.transform().m11()) * factor
        if 1e-9 < effective < 1e6:
            self.scale(factor, factor)

    def to_scene(self, east, north):
        return QPointF(east - self.origin[0], self.origin[1] - north)

    def to_world(self, pos):
        return pos.x() + self.origin[0], self.origin[1] - pos.y()

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        ratio = max(abs(self.transform().m11()), 1e-12)
        raw = 72 / ratio
        step = 10 ** floor(log10(raw))
        step *= next(factor for factor in (1, 2, 5, 10) if factor * step >= raw)
        start_e = ceil((rect.left() + self.origin[0]) / step)
        end_e = floor((rect.right() + self.origin[0]) / step)
        start_n = ceil((self.origin[1] - rect.bottom()) / step)
        end_n = floor((self.origin[1] - rect.top()) / step)
        painter.setPen(self.pen(GRID, 1))
        for idx in range(start_e, end_e + 1):
            x = idx * step - self.origin[0]
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        for idx in range(start_n, end_n + 1):
            y = self.origin[1] - idx * step
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

    def drawForeground(self, painter, rect):
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        if visible.width() <= 0:
            return
        scale = visible.width() / max(self.viewport().width(), 1)
        candidate = scale * 115
        step = 10 ** floor(log10(candidate))
        length = max(f * step for f in (1, 2, 5) if f * step <= candidate)
        painter.save()
        painter.resetTransform()
        painter.setPen(QColor(MUTED))
        y = self.viewport().height() - 17
        painter.drawText(14, y - 8, f"{length:g} ед.")
        painter.drawLine(QPointF(14, y), QPointF(14 + length / scale, y))
        painter.drawText(self.viewport().width() - 67, 23, "↑ NORTH")
        painter.restore()

    def wheelEvent(self, event):
        self.zoom(1.18 if event.angleDelta().y() > 0 else 1 / 1.18)
        event.accept()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        position = event.position().toPoint()
        self.cursor_at.emit(*self.to_world(self.mapToScene(position)))
        if event.buttons() or self.pick_start:
            self.hide_hover()
            return
        item_id = self.object_at(position)
        self.hover_position = position
        if item_id != self.hover_id:
            self.hide_hover()
            self.hover_id = item_id
            if item_id:
                self.hover_timer.start()

    def mousePressEvent(self, event):
        self.hide_hover()
        self.press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    @staticmethod
    def tooltip_text(obj):
        number = str(obj.display_number) if obj.display_number is not None else "Не присвоен"
        return (
            '<p style="white-space:pre; margin:0">'
            f'<span style="color:#AFC5D9">JOIN</span>  <b>{escape(obj.group)}</b><br>'
            '<span style="color:#AFC5D9">Порядковый номер</span>  '
            f'<b>{escape(number)}</b></p>'
        )

    def object_at(self, position, radius=5):
        for item in self.items(position.x() - radius, position.y() - radius, radius * 2, radius * 2):
            key = item.data(0)
            if key in self.lines and item.isVisible():
                return key
        return ""

    def show_hover(self):
        if self.hover_id not in self.lines or self.pick_start:
            return
        item, obj = self.lines[self.hover_id]
        if item.isVisible() and self.object_at(self.hover_position) == self.hover_id:
            QToolTip.showText(
                self.viewport().mapToGlobal(self.hover_position) + QPoint(14, 18),
                self.tooltip_text(obj),
                self.viewport(),
            )

    def hide_hover(self):
        self.hover_timer.stop()
        self.hover_id = ""
        QToolTip.hideText()

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.Leave:
            self.hide_hover()
        elif event.type() == QEvent.Type.ToolTip:
            if self.pick_start:
                return True
            self.hover_position = event.pos()
            self.hover_id = self.object_at(event.pos())
            if self.hover_id:
                self.show_hover()
            else:
                self.hide_hover()
            return True
        return super().viewportEvent(event)

    def mouseReleaseEvent(self, event):
        pos = event.position().toPoint()
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton or (pos - self.press_pos).manhattanLength() > 5:
            return
        if self.pick_start:
            self.pick_start = False
            self.start_picked.emit(*self.to_world(self.mapToScene(pos)))
            return
        item_id = self.object_at(pos, radius=6)
        if item_id:
            self.picked.emit(item_id)

