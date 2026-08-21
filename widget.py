"""Controllers and custom preview widgets for the Qt Designer form."""
from __future__ import annotations

import csv
import math
import sys
from array import array
from pathlib import Path

from angelino import AngelinoCalculator, AngelinoInputs

from PySide6.QtCore import QEvent, QFile, QFileSystemWatcher, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QSurfaceFormat, QVector4D
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLVertexArrayObject
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QMessageBox, QToolTip, QVBoxLayout, QWidget, QSpinBox


PRESSURE_TO_MPA = {"MPa": 1.0, "psi": 0.006894757, "bar": 0.1}
LENGTH_TO_MM = {"mm": 1.0, "inch": 25.4, "m": 1000.0}


class NoWheelFilter(QObject):
    """Lets a containing panel scroll without silently changing an input value."""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel:
            event.ignore()
            return True
        return super().eventFilter(watched, event)


class ContourPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.points: list[tuple[float, float]] = []
        self.lip: list[tuple[float, float]] = []
        self.lip_wall = 0.0
        self.point_mode = "표시 안함"
        self.line_width = 2.0
        self.hit_points: list[tuple[QPoint, int, float, float]] = []
        self.setMinimumHeight(260)
        self.setMouseTracking(True)

    def set_geometry(self, points, lip, lip_wall):
        self.points, self.lip = points, lip
        self.lip_wall = lip_wall
        self.update()

    def set_point_mode(self, mode):
        self.point_mode = mode
        self.update()

    def set_line_width(self, width):
        self.line_width = width
        self.update()

    def visible_indexes(self):
        if self.point_mode == "표시 안함":
            return []
        if self.point_mode == "전체 표시":
            return range(len(self.points))
        return range(0, len(self.points), max(1, math.ceil(len(self.points) / 20)))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#101923"))
        area = self.rect().adjusted(28, 25, -20, -25)

        if not self.points:
            painter.setPen(QColor("#8da0b4"))
            painter.drawText(self.rect(), Qt.AlignCenter, "계산 후 preview가 표시됩니다")
            return

        all_points = self.points + self.lip
        min_x = min(x for x, _ in all_points)
        max_x = max(x for x, _ in all_points)
        span_x = max_x - min_x or 1
        max_radius = max(r for _, r in all_points) + self.lip_wall or 1
        center_y = area.center().y()

        painter.setPen(QPen(QColor("#2c3d4e"), 1))
        painter.drawLine(area.left(), center_y, area.right(), center_y)

        for sign in (-1, 1):
            path = QPainterPath()
            for index, (x, radius) in enumerate(self.points):
                px = area.left() + area.width() * (x - min_x) / span_x
                py = center_y + sign * area.height() * 0.42 * radius / max_radius
                path.moveTo(px, py) if index == 0 else path.lineTo(px, py)
            painter.setPen(QPen(QColor("#45d6b2"), self.line_width))
            painter.drawPath(path)

        for sign in (-1, 1):
            for offset, color, width in ((0, QColor("#f0bd68"), self.line_width * 0.8),
                                         (self.lip_wall, QColor("#d38c42"), self.line_width * 0.67)):
                path = QPainterPath()
                for index, (x, radius) in enumerate(self.lip):
                    px = area.left() + area.width() * (x - min_x) / span_x
                    py = center_y + sign * area.height() * 0.42 * (radius + offset) / max_radius
                    path.moveTo(px, py) if index == 0 else path.lineTo(px, py)
                painter.setPen(QPen(color, width))
                painter.drawPath(path)

        self.hit_points = []
        painter.setPen(QPen(QColor("#45d6b2"), 1))
        painter.setBrush(QColor("#45d6b2"))
        for index in self.visible_indexes():
            x, radius = self.points[index]
            point = QPoint(
                round(area.left() + area.width() * (x - min_x) / span_x),
                round(center_y - area.height() * 0.42 * radius / max_radius),
            )
            painter.drawEllipse(point, 3, 3)
            self.hit_points.append((point, index, x, radius))

    def mouseMoveEvent(self, event):
        cursor = event.position().toPoint()
        nearest = min(self.hit_points, key=lambda item: (item[0] - cursor).manhattanLength(), default=None)
        if nearest and (nearest[0] - cursor).manhattanLength() <= 10:
            _, index, x, radius = nearest
            QToolTip.showText(event.globalPosition().toPoint(), f"#{index}\nx = {x:.5f} mm\nr = {radius:.5f} mm", self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)


class ModelPreview(QOpenGLWidget):
    """Hardware depth-buffer preview, matching conventional CAD navigation."""

    GL_COLOR_BUFFER_BIT = 0x00004000
    GL_DEPTH_BUFFER_BIT = 0x00000100
    GL_DEPTH_TEST = 0x0B71
    GL_MULTISAMPLE = 0x809D
    GL_CULL_FACE = 0x0B44
    GL_BLEND = 0x0BE2
    GL_LEQUAL = 0x0203
    GL_FLOAT = 0x1406
    GL_TRIANGLES = 0x0004
    GL_LINES = 0x0001

    def __init__(self):
        super().__init__()
        self.points = []
        self.lip = []
        self.lip_wall = 0.0
        self.yaw, self.pitch, self.zoom = -0.65, 0.35, 1.0
        self.last = None
        self.show_lip = True
        self.show_plug = True
        self.mode = "Wireframe"
        self.surface_data = array("f")
        self.edge_data = array("f")
        self.surface_count = self.edge_count = 0
        self.surface_buffer = None
        self.edge_buffer = None
        self.vertex_array = None
        self.program = None
        self.geometry_dirty = True
        self.min_x, self.max_x, self.max_radius, self.depth_extent = -1, 1, 1, 1
        surface_format = QSurfaceFormat()
        surface_format.setDepthBufferSize(24)
        surface_format.setSamples(4)
        self.setFormat(surface_format)
        self.setMinimumHeight(260)
        self.setCursor(Qt.OpenHandCursor)

    def set_geometry(self, points, lip, lip_wall):
        self.points, self.lip = points, lip
        self.lip_wall = lip_wall
        self.rebuild_geometry()
        self.update()

    def set_mode(self, mode):
        self.mode = mode
        self.update()

    def set_visibility(self, lip, plug):
        self.show_lip, self.show_plug = lip, plug
        self.rebuild_geometry()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.last is not None:
            delta = event.position().toPoint() - self.last
            self.yaw -= delta.x() * 0.012
            self.pitch = max(-1.35, min(1.35, self.pitch + delta.y() * 0.012))
            self.last = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        self.last = None
        self.setCursor(Qt.OpenHandCursor)
        self.update()

    def wheelEvent(self, event):
        self.zoom = max(0.35, min(2.8, self.zoom * math.pow(1.0015, event.angleDelta().y())))
        self.update()

    @staticmethod
    def add_vertex(target, point, color, normal):
        target.extend((*point, color.redF(), color.greenF(), color.blueF(), *normal))

    def add_face(self, vertices, color):
        first, second, third = vertices[:3]
        u = tuple(b - a for a, b in zip(first, second))
        v = tuple(b - a for a, b in zip(first, third))
        normal = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        length = math.sqrt(sum(component * component for component in normal)) or 1
        normal = tuple(component / length for component in normal)
        for index in range(1, len(vertices) - 1):
            for vertex in (vertices[0], vertices[index], vertices[index + 1]):
                self.add_vertex(self.surface_data, vertex, color, normal)
        edge_color = color.darker(170)
        for index, vertex in enumerate(vertices):
            self.add_vertex(self.edge_data, vertex, edge_color, normal)
            self.add_vertex(self.edge_data, vertices[(index + 1) % len(vertices)], edge_color, normal)

    def rebuild_geometry(self):
        self.surface_data = array("f")
        self.edge_data = array("f")
        all_points = self.points + self.lip
        if not all_points:
            self.surface_count = self.edge_count = 0
            self.geometry_dirty = True
            return
        self.min_x = min(x for x, _ in all_points)
        self.max_x = max(x for x, _ in all_points)
        self.max_radius = max([radius for _, radius in self.points] + [radius + self.lip_wall for _, radius in self.lip])
        center_x = (self.min_x + self.max_x) / 2
        self.depth_extent = max(1.0, max(math.hypot(x - center_x, radius + (self.lip_wall if is_lip else 0)) for profile, is_lip in ((self.lip, True), (self.points, False)) for x, radius in profile))
        profiles = ((self.lip, self.lip_wall, True, QColor("#f0a44c")),
                    (self.points, 0.0, False, QColor("#45d6b2")))
        segments = 48
        for profile, wall, is_lip, color in profiles:
            if (is_lip and not self.show_lip) or (not is_lip and not self.show_plug):
                continue
            step = max(1, len(profile) // 48)
            rows = profile[::step]
            if rows[-1] != profile[-1]:
                rows.append(profile[-1])
            outer = [[(x - center_x, (radius + wall if is_lip else radius) * math.cos(2 * math.pi * segment / segments), (radius + wall if is_lip else radius) * math.sin(2 * math.pi * segment / segments)) for segment in range(segments)] for x, radius in rows]
            inner = [[(x - center_x, radius * math.cos(2 * math.pi * segment / segments), radius * math.sin(2 * math.pi * segment / segments)) for segment in range(segments)] for x, radius in rows] if is_lip else None
            for mesh, inward in ((outer, False), (inner, True)) if is_lip else ((outer, False),):
                for row in range(len(mesh) - 1):
                    for segment in range(segments):
                        face = (mesh[row][segment], mesh[row][(segment + 1) % segments], mesh[row + 1][(segment + 1) % segments], mesh[row + 1][segment])
                        self.add_face(tuple(reversed(face)) if inward else face, color)
            for ring in (0, -1):
                for segment in range(segments):
                    if is_lip:
                        face = (outer[ring][segment], outer[ring][(segment + 1) % segments], inner[ring][(segment + 1) % segments], inner[ring][segment])
                    else:
                        face = ((rows[ring][0] - center_x, 0, 0), outer[ring][segment], outer[ring][(segment + 1) % segments])
                    self.add_face(tuple(reversed(face)) if ring == 0 else face, color)
        self.surface_count = len(self.surface_data) // 9
        self.edge_count = len(self.edge_data) // 9
        self.geometry_dirty = True

    def initializeGL(self):
        self.program = QOpenGLShaderProgram(self)
        vertex_shader = """
            attribute vec3 position;
            attribute vec3 color;
            attribute vec3 normal;
            uniform vec4 view;
            uniform vec4 camera;
            varying vec3 fragmentColor;
            varying float illumination;
            void main() {
                float yaw = view.x, pitch = view.y, aspect = view.z;
                float cy = cos(yaw), sy = sin(yaw);
                vec3 turned = vec3(position.x * cy - position.z * sy, position.y, position.x * sy + position.z * cy);
                vec3 turnedNormal = vec3(normal.x * cy - normal.z * sy, normal.y, normal.x * sy + normal.z * cy);
                float cp = cos(pitch), sp = sin(pitch);
                vec3 rotated = vec3(turned.x, turned.y * cp - turned.z * sp, turned.y * sp + turned.z * cp);
                vec3 rotatedNormal = vec3(turnedNormal.x, turnedNormal.y * cp - turnedNormal.z * sp, turnedNormal.y * sp + turnedNormal.z * cp);
                float focal = camera.x, distance = camera.y, nearPlane = camera.z, farPlane = camera.w;
                vec3 eye = rotated - vec3(0.0, 0.0, distance);
                float a = (farPlane + nearPlane) / (nearPlane - farPlane);
                float b = 2.0 * farPlane * nearPlane / (nearPlane - farPlane);
                gl_Position = vec4(eye.x * focal / aspect, eye.y * focal, a * eye.z + b, -eye.z);
                fragmentColor = color;
                illumination = 0.32 + 0.68 * max(dot(normalize(rotatedNormal), normalize(vec3(-0.35, 0.55, 0.75))), 0.0);
            }
        """
        fragment_shader = """
            varying vec3 fragmentColor;
            varying float illumination;
            void main() { gl_FragColor = vec4(fragmentColor * illumination, 1.0); }
        """
        if not self.program.addShaderFromSourceCode(QOpenGLShader.Vertex, vertex_shader) or not self.program.addShaderFromSourceCode(QOpenGLShader.Fragment, fragment_shader) or not self.program.link():
            raise RuntimeError(f"OpenGL shader setup failed: {self.program.log()}")
        self.uniforms = {name: self.program.uniformLocation(name.encode()) for name in ("view", "camera")}
        self.attributes = {name: self.program.attributeLocation(name.encode()) for name in ("position", "color", "normal")}
        self.surface_buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.edge_buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self.vertex_array = QOpenGLVertexArrayObject(self)
        self.vertex_array.create()
        self.surface_buffer.create()
        self.edge_buffer.create()

    def resizeGL(self, width, height):
        self.context().functions().glViewport(0, 0, width, height)

    def upload_geometry(self):
        for buffer, data in ((self.surface_buffer, self.surface_data), (self.edge_buffer, self.edge_data)):
            raw = data.tobytes()
            buffer.bind()
            buffer.allocate(len(raw))
            buffer.write(0, raw, len(raw))
            buffer.release()
        self.geometry_dirty = False

    def draw_buffer(self, buffer, count, primitive):
        if not count:
            return
        functions = self.context().functions()
        self.vertex_array.bind()
        buffer.bind()
        self.program.enableAttributeArray(self.attributes["position"])
        self.program.enableAttributeArray(self.attributes["color"])
        self.program.enableAttributeArray(self.attributes["normal"])
        self.program.setAttributeBuffer(self.attributes["position"], self.GL_FLOAT, 0, 3, 36)
        self.program.setAttributeBuffer(self.attributes["color"], self.GL_FLOAT, 12, 3, 36)
        self.program.setAttributeBuffer(self.attributes["normal"], self.GL_FLOAT, 24, 3, 36)
        functions.glDrawArrays(primitive, 0, count)
        buffer.release()
        self.vertex_array.release()

    def paintGL(self):
        functions = self.context().functions()
        functions.glClearColor(16 / 255, 25 / 255, 35 / 255, 1)
        functions.glClearDepthf(1.0)
        functions.glClear(self.GL_COLOR_BUFFER_BIT | self.GL_DEPTH_BUFFER_BIT)
        if not self.surface_count:
            return
        if self.geometry_dirty:
            self.upload_geometry()
        functions.glEnable(self.GL_DEPTH_TEST)
        functions.glEnable(self.GL_MULTISAMPLE)
        functions.glDepthFunc(self.GL_LEQUAL)
        functions.glDepthMask(True)
        functions.glDisable(self.GL_BLEND)
        functions.glDisable(self.GL_CULL_FACE)
        self.program.bind()
        aspect = max(self.width() / max(self.height(), 1), 0.1)
        width = max(self.max_x - self.min_x, 1)
        fit_scale = min(2 * aspect / (width * 1.35), 2 / (self.max_radius * 2.8))
        distance = self.depth_extent * 4
        focal = fit_scale * distance * self.zoom
        near_plane = max(0.1, distance - self.depth_extent * 1.1)
        far_plane = distance + self.depth_extent * 1.1
        self.program.setUniformValue(self.uniforms["view"], QVector4D(self.yaw, self.pitch, aspect, 0))
        self.program.setUniformValue(self.uniforms["camera"], QVector4D(focal, distance, near_plane, far_plane))
        if self.mode != "Wireframe":
            self.draw_buffer(self.surface_buffer, self.surface_count, self.GL_TRIANGLES)
        if self.mode != "Smooth surface":
            functions.glLineWidth(1.0)
            self.draw_buffer(self.edge_buffer, self.edge_count, self.GL_LINES)
        self.program.release()

class App:
    def __init__(self):
        self.form_path = Path(__file__).with_name("form.ui")
        self.window = self.load_form()
        self.calculator = AngelinoCalculator()
        self.points = []
        self.lip_points = []
        self.lip_outer_points = []
        self.setup_units()
        self.setup_previews()
        self.connect_signals()
        self.ui_watcher = QFileSystemWatcher([str(self.form_path)])
        self.ui_watcher.fileChanged.connect(self.schedule_ui_reload)

    def load_form(self):
        source = QFile(str(self.form_path))
        source.open(QFile.ReadOnly)
        window = QUiLoader().load(source)
        source.close()
        if window is None:
            raise RuntimeError("form.ui를 불러올 수 없습니다.")
        return window

    def schedule_ui_reload(self):
        """Reload Designer changes immediately after a complete file save."""
        QTimer.singleShot(150, self.reload_form)

    def reload_form(self):
        if not self.form_path.exists():
            return
        previous = self.window
        geometry = previous.geometry()
        try:
            self.window = self.load_form()
            self.setup_units()
            self.setup_previews()
            self.connect_signals()
        except RuntimeError:
            self.window = previous
            return
        self.window.setGeometry(geometry)
        self.window.show()
        previous.close()
        previous.deleteLater()
        if str(self.form_path) not in self.ui_watcher.files():
            self.ui_watcher.addPath(str(self.form_path))

    def ui(self, name):
        widget = self.window.findChild(QWidget, name)
        if widget is None:
            raise RuntimeError(f"form.ui에 {name} 위젯이 없습니다.")
        return widget

    def setup_previews(self):
        self.contour = ContourPreview()
        self.model = ModelPreview()
        self.lip_visible = self.ui("lipVisible")
        self.plug_visible = self.ui("plugVisible")
        self.model.set_mode(self.ui("renderModeCombo").currentText())
        self.contour.set_line_width(self.ui("contourLineWidthSpin").value())
        for host_name, preview in (("contourHost", self.contour), ("modelHost", self.model)):
            layout = QVBoxLayout(self.ui(host_name))
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(preview)

    def setup_units(self):
        self.pressure_unit = self.ui("pressureUnitCombo")
        self.length_unit = self.ui("lengthUnitCombo")
        self.exit_pressure_spin = self.ui("exitPressureSpin")
        self.throat_area_spin = self.ui("throatAreaSpin")
        self.lip_wall_spin = self.ui("lipWallSpin")
        self.lip_pipe_radius_spin = self.ui("lipPipeRadiusSpin")
        self.plug_column_length_spin = self.ui("plugColumnLengthSpin")
        self.plug_column_radius_spin = self.ui("plugColumnRadiusSpin")
        self.plug_converging_length_spin = self.ui("plugConvergingLengthSpin")
        self.throat_length_spin = self.ui("throatLengthSpin")
        self.me_value = self.ui("meValue")
        self.pressure_factor = 1.0
        self.length_factor = 1.0
        self.wheel_filter = NoWheelFilter(self.window)
        for field in (*self.window.findChildren(QDoubleSpinBox), *self.window.findChildren(QSpinBox), *self.window.findChildren(QComboBox)):
            field.installEventFilter(self.wheel_filter)

    def connect_signals(self):
        self.ui("angelinoButton").clicked.connect(lambda: self.ui("pages").setCurrentIndex(1))
        self.ui("backButton").clicked.connect(lambda: self.ui("pages").setCurrentIndex(0))
        self.ui("calculateButton").clicked.connect(self.calculate)
        self.ui("exportButton").clicked.connect(self.export)
        self.ui("renderModeCombo").currentTextChanged.connect(self.model.set_mode)
        self.lip_visible.toggled.connect(self.update_model_visibility)
        self.plug_visible.toggled.connect(self.update_model_visibility)
        self.ui("pointDisplayCombo").currentTextChanged.connect(self.contour.set_point_mode)
        self.ui("contourLineWidthApplyButton").clicked.connect(
            lambda: self.contour.set_line_width(self.ui("contourLineWidthSpin").value())
        )
        self.pressure_unit.currentTextChanged.connect(self.update_pressure_unit)
        self.length_unit.currentTextChanged.connect(self.update_length_unit)

    def update_pressure_unit(self, unit):
        factor = PRESSURE_TO_MPA[unit]
        for spin, minimum in ((self.ui("pressureSpin"), 0.01), (self.exit_pressure_spin, 0.000001)):
            physical_value = spin.value() * self.pressure_factor
            spin.setRange(minimum / factor, 100 / factor)
            spin.setValue(physical_value / factor)
            spin.setSuffix(f" {unit}")
        self.pressure_factor = factor

    def update_length_unit(self, unit):
        factor = LENGTH_TO_MM[unit]
        fields = ((self.ui("throatSpin"), 0.2, 1000), (self.lip_pipe_radius_spin, 0.2, 2000),
                  (self.plug_column_length_spin, 0.1, 1000), (self.plug_column_radius_spin, 0.2, 2000),
                  (self.plug_converging_length_spin, 0.1, 1000), (self.throat_length_spin, 0, 1000),
                  (self.lip_wall_spin, 0.01, 1000))
        for spin, minimum, maximum in fields:
            physical_value = spin.value() * self.length_factor
            spin.setRange(minimum / factor, maximum / factor)
            spin.setValue(physical_value / factor)
            spin.setSuffix(f" {unit}")
        self.length_factor = factor

    def pressure_mpa(self, spin):
        return spin.value() * PRESSURE_TO_MPA[self.pressure_unit.currentText()]

    def update_model_visibility(self):
        self.model.set_visibility(self.lip_visible.isChecked(), self.plug_visible.isChecked())

    def length_to_mm(self, value):
        return value * LENGTH_TO_MM[self.length_unit.currentText()]

    def calculate(self):
        inputs = AngelinoInputs(
            self.pressure_mpa(self.ui("pressureSpin")),
            self.pressure_mpa(self.exit_pressure_spin),
            self.length_to_mm(self.ui("throatSpin").value()) / 2,
            self.throat_area_spin.value(),
            self.ui("machSpin").value(),
            self.ui("truncationSpin").value(),
            self.ui("pointSpin").value(),
            self.length_to_mm(self.lip_pipe_radius_spin.value()) / 2,
            self.length_to_mm(self.plug_column_length_spin.value()),
            self.length_to_mm(self.plug_column_radius_spin.value()) / 2,
            self.length_to_mm(self.plug_converging_length_spin.value()),
            self.length_to_mm(self.throat_length_spin.value()),
            self.length_to_mm(self.lip_wall_spin.value()),
        )
        try:
            result = self.calculator.calculate(inputs)
        except (ValueError, ZeroDivisionError) as error:
            dialog = QMessageBox(QMessageBox.Warning, "계산 불가", f"입력값을 확인하세요.\n{error}", parent=self.window)
            dialog.setStyleSheet("QLabel{color:#1f2933;}")
            dialog.exec()
            return
        self.points = result.aerospike
        self.lip_points = result.lip
        self.lip_outer_points = [(x, radius + result.lip_wall_thickness_mm) for x, radius in result.lip]
        self.contour.set_geometry(result.aerospike, result.lip, result.lip_wall_thickness_mm)
        self.model.set_geometry(result.aerospike, result.lip, result.lip_wall_thickness_mm)
        self.me_value.setText(f"{result.design_exit_mach:.5f}")
        rows = [
            "Angelino 1964 approximate axisymmetric plug nozzle",
            f"design pressure ratio (p0/pe), {result.design_pressure_ratio:.5f}",
            f"design exit pressure, {inputs.exit_pressure_mpa:.6f} MPa",
            f"design exit Mach, {result.design_exit_mach:.5f}",
            f"throat angle, {result.throat_angle_deg:.5f} deg",
            f"geometric throat area, {result.throat_area_mm2:.5f} mm^2",
            f"Lip exit radius, {result.lip_radius_mm:.5f} mm",
            f"Plug base radius, {result.base_radius_mm:.5f} mm",
            f"Plug converging length, {inputs.plug_converging_length_mm:.5f} mm",
            f"constant annular throat length lₜ, {result.throat_gap_length_mm:.5f} mm",
            f"Mach sweep, M=1.00000 → Me={result.design_exit_mach:.5f}",
            f"Mach sweep / contour samples, {inputs.contour_points}",
            "",
            "part, index, x_mm, r_mm",
        ]
        rows += [f"Lip inner, {index:03d}, {x:.5f}, {radius:.5f}" for index, (x, radius) in enumerate(self.lip_points)]
        rows += [f"Lip outer, {index:03d}, {x:.5f}, {radius:.5f}" for index, (x, radius) in enumerate(self.lip_outer_points)]
        rows += [f"Plug, {index:03d}, {x:.5f}, {radius:.5f}" for index, (x, radius) in enumerate(self.points)]
        self.ui("coordinatesText").setPlainText("\n".join(rows))
        self.ui("statusLabel").setText(
            f"✓ M=1→{result.design_exit_mach:.3f} 스위프 완료 | Lip {len(self.lip_points)}개 + Plug {len(self.points)}개 좌표"
        )
        self.ui("designTabs").setCurrentIndex(1)

    def export(self):
        if not self.points:
            QMessageBox.information(self.window, "내보낼 데이터 없음", "먼저 contour를 계산하세요.")
            return
        path, _ = QFileDialog.getSaveFileName(self.window, "Contour 좌표 저장", "angelino_contour.csv", "CSV Files (*.csv)")
        if not path:
            return
        with Path(path).open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["part", "index", "x_mm", "r_mm"])
            writer.writerows(("Lip inner", index, f"{x:.7f}", f"{radius:.7f}") for index, (x, radius) in enumerate(self.lip_points))
            writer.writerows(("Lip outer", index, f"{x:.7f}", f"{radius:.7f}") for index, (x, radius) in enumerate(self.lip_outer_points))
            writer.writerows(("Plug", index, f"{x:.7f}", f"{radius:.7f}") for index, (x, radius) in enumerate(self.points))
        self.ui("statusLabel").setText(f"✓ 좌표 파일 저장 완료: {Path(path).name}")


if __name__ == "__main__":
    application = QApplication(sys.argv)
    application.setStyle("Fusion")
    app = App()
    app.window.show()
    sys.exit(application.exec())
