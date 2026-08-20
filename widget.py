"""Controllers and custom preview widgets for the Qt Designer form."""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

from angelino import AngelinoCalculator, AngelinoInputs

from PySide6.QtCore import QFile, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QBoxLayout, QHBoxLayout, QLabel, QMessageBox, QScrollArea, QTabWidget, QToolTip,
    QVBoxLayout, QWidget,
)


PRESSURE_TO_MPA = {"MPa": 1.0, "psi": 0.006894757, "bar": 0.1}
LENGTH_TO_MM = {"mm": 1.0, "inch": 25.4, "m": 1000.0}


class NoWheelComboBox(QComboBox):
    """Keeps a value selected while the user scrolls a surrounding panel."""

    def wheelEvent(self, event):
        event.ignore()


class FixedSuffixSpinBox(QDoubleSpinBox):
    """A left-aligned value with a unit label pinned to the field's right edge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.unit = ""
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def setSuffix(self, suffix):
        self.unit = suffix.strip()
        self.lineEdit().setTextMargins(0, 0, max(0, self.fontMetrics().horizontalAdvance(self.unit) + 12), 0)
        super().setSuffix("")
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.unit:
            return
        painter = QPainter(self)
        painter.setPen(QColor("#9eb3c8"))
        button_width = 22
        text_area = self.rect().adjusted(4, 0, -button_width - 5, 0)
        painter.drawText(text_area, Qt.AlignRight | Qt.AlignVCenter, self.unit)


class ResponsiveGroups(QWidget):
    """Places input groups side-by-side, then stacks them on narrow viewports."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(12)

    def add_group(self, group):
        self.layout.addWidget(group, 1)

    def resizeEvent(self, event):
        direction = QBoxLayout.LeftToRight if self.width() >= 720 else QBoxLayout.TopToBottom
        if self.layout.direction() != direction:
            self.layout.setDirection(direction)
        super().resizeEvent(event)


class ShapeCard(QFrame):
    selected = Signal(str)

    def __init__(self, name: str, description: str, available: bool):
        super().__init__()
        self.name = name
        self.available = available
        self.setObjectName("shapeCard")
        self.setCursor(Qt.PointingHandCursor if available else Qt.ForbiddenCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(9)

        title = QLabel(name)
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        detail = QLabel(description)
        detail.setObjectName("cardText")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        layout.addStretch()

        badge = QLabel("개발 가능" if available else "추후 지원")
        badge.setObjectName("availableBadge" if available else "soonBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedWidth(72)
        layout.addWidget(badge, alignment=Qt.AlignLeft)

    def mousePressEvent(self, event):
        if self.available:
            self.selected.emit(self.name)
        super().mousePressEvent(event)


class ContourPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.points: list[tuple[float, float]] = []
        self.lip: list[tuple[float, float]] = []
        self.wall = 0.0
        self.point_mode = "표시 안함"
        self.hit_points: list[tuple[QPoint, int, float, float]] = []
        self.setMinimumHeight(260)
        self.setMouseTracking(True)

    def set_geometry(self, points, lip, wall):
        self.points, self.lip, self.wall = points, lip, wall
        self.update()

    def set_point_mode(self, mode):
        self.point_mode = mode
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
        max_radius = max(r for _, r in all_points) + self.wall or 1
        center_y = area.center().y()

        painter.setPen(QPen(QColor("#2c3d4e"), 1))
        painter.drawLine(area.left(), center_y, area.right(), center_y)

        for sign in (-1, 1):
            path = QPainterPath()
            for index, (x, radius) in enumerate(self.points):
                px = area.left() + area.width() * (x - min_x) / span_x
                py = center_y + sign * area.height() * 0.42 * radius / max_radius
                path.moveTo(px, py) if index == 0 else path.lineTo(px, py)
            painter.setPen(QPen(QColor("#45d6b2"), 3))
            painter.drawPath(path)

        for sign in (-1, 1):
            for offset, color, width in ((0, QColor("#f0bd68"), 2.4), (self.wall, QColor("#d38c42"), 2.0)):
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


class ModelPreview(QWidget):
    """Opaque, turntable-style preview of a wall-thickness-aware surface."""

    def __init__(self):
        super().__init__()
        self.points = []
        self.lip = []
        self.wall = 0.0
        self.yaw, self.pitch, self.zoom = -0.65, 0.35, 1.0
        self.last = None
        self.mode = "Wireframe"
        self.setMinimumHeight(260)
        self.setCursor(Qt.OpenHandCursor)

    def set_geometry(self, points, lip, wall):
        self.points, self.lip, self.wall = points, lip, wall
        self.update()

    def set_mode(self, mode):
        self.mode = mode
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.last is not None:
            delta = event.position().toPoint() - self.last
            self.yaw += delta.x() * 0.012
            self.pitch = max(-1.35, min(1.35, self.pitch - delta.y() * 0.012))
            self.last = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        self.last = None
        self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, event):
        self.zoom = max(0.35, min(2.8, self.zoom * math.pow(1.0015, event.angleDelta().y())))
        self.update()

    def project(self, x, y, z, scale, center_x, center_y):
        xx = x * math.cos(self.yaw) - z * math.sin(self.yaw)
        zz = x * math.sin(self.yaw) + z * math.cos(self.yaw)
        yy = y * math.cos(self.pitch) - zz * math.sin(self.pitch)
        depth = y * math.sin(self.pitch) + zz * math.cos(self.pitch)
        return QPoint(round(center_x + xx * scale), round(center_y - yy * scale)), depth

    @staticmethod
    def append_visible_face(faces, vertices):
        points = [point for point, _ in vertices]
        signed_area = sum(points[k].x() * points[(k + 1) % 4].y() - points[(k + 1) % 4].x() * points[k].y() for k in range(4))
        if signed_area > 0:
            faces.append((sum(depth for _, depth in vertices) / 4, points))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#101923"))
        if not self.points:
            painter.setPen(QColor("#8da0b4"))
            painter.drawText(self.rect(), Qt.AlignCenter, "계산 후 3D preview가 표시됩니다")
            return

        profiles = ((self.lip, True), (self.points, False))
        all_points = [point for profile, _ in profiles for point in profile]
        min_x, max_x = min(x for x, _ in all_points), max(x for x, _ in all_points)
        width = max_x - min_x or 1
        max_radius = max(r for _, r in all_points) + self.wall
        scale = min(self.width() / (width * 1.35), self.height() / (max_radius * 2.8)) * self.zoom
        segments = 28
        meshes, faces = [], []
        for profile, is_lip in profiles:
            step = max(1, len(profile) // 28)
            rows = profile[::step]
            if rows[-1] != profile[-1]:
                rows.append(profile[-1])
            mesh = []
            for x, radius in rows:
                center = x - (min_x + max_x) / 2
                physical_radius = radius + self.wall if is_lip else radius
                mesh.append([self.project(center, physical_radius * math.cos(2 * math.pi * j / segments), physical_radius * math.sin(2 * math.pi * j / segments), scale, self.width() / 2, self.height() / 2) for j in range(segments)])
            meshes.append(mesh)
            for row in range(len(mesh) - 1):
                for segment in range(segments):
                    self.append_visible_face(faces, [mesh[row][segment], mesh[row][(segment + 1) % segments], mesh[row + 1][(segment + 1) % segments], mesh[row + 1][segment]])

        if self.mode != "Wireframe":
            # Adjacent antialiased polygons leave hairline gaps on some Qt
            # backends.  Disable antialiasing while the opaque shell is
            # composited; otherwise the gaps resemble unwanted wireframe
            # edges in Smooth surface mode.
            painter.setRenderHint(QPainter.Antialiasing, False)
            painter.setPen(Qt.NoPen)
            for depth, vertices in sorted(faces, key=lambda face: face[0]):
                path = QPainterPath(vertices[0])
                for point in vertices[1:]:
                    path.lineTo(point)
                path.closeSubpath()
                painter.fillPath(path, QColor("#45d6b2"))

            painter.setRenderHint(QPainter.Antialiasing)

        if self.mode == "Wireframe":
            painter.setPen(QPen(QColor("#56d5d1"), 1.1))
            for mesh in meshes:
                for row in mesh:
                    for segment in range(segments):
                        painter.drawLine(row[segment][0], row[(segment + 1) % segments][0])
                for segment in range(0, segments, 2):
                    for row in range(len(mesh) - 1):
                        painter.drawLine(mesh[row][segment][0], mesh[row + 1][segment][0])
        elif self.mode == "Surface with edges":
            painter.setPen(QPen(QColor("#176f65"), 0.7))
            for _, vertices in faces:
                for index in range(4):
                    painter.drawLine(vertices[index], vertices[(index + 1) % 4])


class App:
    def __init__(self):
        self.window = self.load_form()
        self.calculator = AngelinoCalculator()
        self.points = []
        self.lip_points = []
        self.lip_outer_points = []
        self.setup_units()
        self.setup_previews()
        self.build_shape_cards()
        self.organize_design_tabs()
        self.connect_signals()

    def load_form(self):
        source = QFile(str(Path(__file__).with_name("form.ui")))
        source.open(QFile.ReadOnly)
        window = QUiLoader().load(source)
        source.close()
        if window is None:
            raise RuntimeError("form.ui를 불러올 수 없습니다.")
        return window

    def ui(self, name):
        widget = self.window.findChild(QWidget, name)
        if widget is None:
            raise RuntimeError(f"form.ui에 {name} 위젯이 없습니다.")
        return widget

    def setup_previews(self):
        self.contour = ContourPreview()
        self.model = ModelPreview()
        for host_name, preview in (("contourHost", self.contour), ("modelHost", self.model)):
            layout = QVBoxLayout(self.ui(host_name))
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(preview)

    def organize_design_tabs(self):
        """Separates growing design inputs from combined visual/data results."""
        design_layout = self.window.findChild(QVBoxLayout, "designLayout")
        splitter = self.ui("mainSplitter")
        input_panel, results_panel = splitter.widget(0), splitter.widget(1)

        input_scroll = QScrollArea()
        input_scroll.setWidgetResizable(True)
        input_scroll.setFrameShape(QFrame.NoFrame)
        input_scroll.setStyleSheet("QScrollArea { background: #0b121a; border: none; }")
        input_scroll.setWidget(input_panel)

        tabs = QTabWidget()
        tabs.setObjectName("designTabs")
        tabs.addTab(input_scroll, "설계 입력값")
        tabs.addTab(results_panel, "계산 결과")
        design_layout.replaceWidget(splitter, tabs)
        splitter.deleteLater()

    def build_shape_cards(self):
        layout = self.window.findChild(QHBoxLayout, "shapeCardsLayout")
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        cards = [
            ("Plug nozzle (Angelino)", "Angelino 논문의 중심 Plug contour와 Lip을 계산합니다. 고도 보상 특성을 목표로 하는 설계 방식입니다.", True),
            ("Aerospike (MOC)", "특성선법(Method of Characteristics)으로 형상을 구성하는 aerospike 방식입니다.", False),
            ("Bell (Rao)", "짧고 효율적인 bell nozzle contour를 만드는 고전적 최적화 방식입니다.", False),
            ("Bell (MOC)", "특성선법을 이용한 axisymmetric bell nozzle 설계입니다.", False),
            ("Conical", "반각과 길이로 정의하는 단순하고 제작 친화적인 원추형 노즐입니다.", False),
        ]
        for name, description, available in cards:
            card = ShapeCard(name, description, available)
            card.selected.connect(lambda _: self.ui("pages").setCurrentIndex(1))
            layout.addWidget(card)

    def setup_units(self):
        form = self.window.findChild(QFormLayout, "inputForm")
        for name in ("pressureSpin", "altitudeSpin", "throatSpin", "machSpin", "truncationSpin"):
            self.upgrade_double_spin(form, name)
        self.pressure_unit = NoWheelComboBox()
        self.pressure_unit.addItems(["MPa", "psi", "bar"])
        self.length_unit = NoWheelComboBox()
        self.length_unit.addItems(["mm", "inch", "m"])
        self.wall_spin = FixedSuffixSpinBox()
        self.wall_spin.setRange(0.00001, 1000)
        self.wall_spin.setValue(2)
        self.wall_spin.setDecimals(5)
        self.lip_pipe_length_spin = FixedSuffixSpinBox()
        self.lip_pipe_length_spin.setRange(0.1, 1000)
        self.lip_pipe_length_spin.setValue(30)
        self.lip_pipe_length_spin.setDecimals(5)
        self.lip_pipe_radius_spin = FixedSuffixSpinBox()
        self.lip_pipe_radius_spin.setRange(0.1, 1000)
        self.lip_pipe_radius_spin.setValue(28)
        self.lip_pipe_radius_spin.setDecimals(5)
        self.plug_column_length_spin = FixedSuffixSpinBox()
        self.plug_column_length_spin.setRange(0.1, 1000)
        self.plug_column_length_spin.setValue(20)
        self.plug_column_length_spin.setDecimals(5)
        self.plug_column_radius_spin = FixedSuffixSpinBox()
        self.plug_column_radius_spin.setRange(0.1, 1000)
        self.plug_column_radius_spin.setValue(16)
        self.plug_column_radius_spin.setDecimals(5)
        self.ui("machSpin").setRange(1.05, 1.67)
        self.ui("machSpin").setValue(1.22)
        self.ui("machSpin").setDecimals(3)
        self.ui("machSpin").setSuffix("")
        form.addRow("압력 단위", self.pressure_unit)
        form.addRow("길이 단위", self.length_unit)
        form.addRow("노즐 벽 두께", self.wall_spin)
        self.pressure_factor = 1.0
        self.length_factor = 1.0
        self.update_length_unit("mm")
        self.align_input_fields()
        self.rebuild_input_groups(form)

    def upgrade_double_spin(self, form, name):
        """Replaces a Designer spinbox with a field that pins its suffix right."""
        old = self.ui(name)
        row, role = form.getWidgetPosition(old)
        replacement = FixedSuffixSpinBox()
        replacement.setObjectName(name)
        replacement.setRange(old.minimum(), old.maximum())
        replacement.setDecimals(old.decimals())
        replacement.setSingleStep(old.singleStep())
        replacement.setValue(old.value())
        replacement.setSuffix(old.suffix())
        form.setWidget(row, role, replacement)
        old.setParent(None)
        old.deleteLater()

    def align_input_fields(self):
        """Pins values and their suffixes to the right side of each input control."""
        field_names = (
            "pressureSpin",
            "altitudeSpin",
            "throatSpin",
            "machSpin",
            "truncationSpin",
            "pointSpin",
            "sweepSpin",
        )
        for name in field_names:
            self.ui(name).setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def rebuild_input_groups(self, basic_form):
        """Groups forms horizontally without allowing a horizontal scroll area."""
        input_layout = self.window.findChild(QVBoxLayout, "inputLayout")
        precision_form = self.window.findChild(QFormLayout, "precisionForm")
        # The Designer stylesheet overrides some label object names, so use their
        # stable positions in the original input layout rather than object names.
        title = input_layout.itemAt(0).widget()
        old_basic_label = input_layout.itemAt(1).widget()
        old_precision_label = input_layout.itemAt(3).widget()
        help_text = input_layout.itemAt(5).widget()
        calculate_button = self.ui("calculateButton")

        self.hide_form_labels(basic_form)
        self.hide_form_labels(precision_form)
        help_text.setText("유동 방향은 +x입니다. Lip은 straight pipe 뒤에 νe로 꺾이는 수렴부이며, Plug 기둥과 Angelino contour는 별도 형상입니다.")

        while input_layout.count():
            input_layout.takeAt(0)

        old_basic_label.hide()
        old_precision_label.hide()
        old_basic_label.deleteLater()
        old_precision_label.deleteLater()

        groups = ResponsiveGroups()
        primary_form = QFormLayout()
        primary_form.addRow("연소실 정체압 p₀", self.ui("pressureSpin"))
        primary_form.addRow("설계 고도", self.ui("altitudeSpin"))
        primary_form.addRow("Plug contour 시작 반지름", self.ui("throatSpin"))
        primary_form.addRow("비열비 γ", self.ui("machSpin"))
        primary_form.addRow("Plug truncation", self.ui("truncationSpin"))
        primary_form.addRow("Lip straight pipe 길이", self.lip_pipe_length_spin)
        primary_form.addRow("Lip pipe 반지름", self.lip_pipe_radius_spin)
        primary_form.addRow("Plug 기둥 길이", self.plug_column_length_spin)
        primary_form.addRow("Plug 기둥 반지름", self.plug_column_radius_spin)
        primary_form.addRow("압력 단위", self.pressure_unit)
        primary_form.addRow("길이 단위", self.length_unit)
        primary_form.addRow("노즐 벽 두께", self.wall_spin)
        groups.add_group(self.make_input_group("Plug 설계 조건", primary_form))

        resolution_form = QFormLayout()
        resolution_form.addRow("Plug contour points", self.ui("pointSpin"))
        resolution_layout = QVBoxLayout()
        resolution_layout.setContentsMargins(0, 0, 0, 0)
        self.ui("sweepSpin").hide()
        resolution_layout.addLayout(resolution_form)
        resolution_layout.addWidget(help_text)
        groups.add_group(self.make_input_group("해상도 / 계산 정밀도", resolution_layout))

        input_layout.addWidget(title)
        input_layout.addWidget(groups)
        input_layout.addStretch()
        input_layout.addWidget(calculate_button)

    @staticmethod
    def hide_form_labels(form):
        """Old Designer labels must not remain visible after fields are reparented."""
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.LabelRole)
            if item and item.widget():
                item.widget().hide()


    @staticmethod
    def make_input_group(title_text, content):
        group = QFrame()
        group.setObjectName("inputGroup")
        group.setMinimumWidth(310)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 12, 14, 14)
        title = QLabel(title_text)
        title.setObjectName("group")
        layout.addWidget(title)
        layout.addLayout(content)
        return group

    def connect_signals(self):
        self.ui("backButton").clicked.connect(lambda: self.ui("pages").setCurrentIndex(0))
        self.ui("calculateButton").clicked.connect(self.calculate)
        self.ui("exportButton").clicked.connect(self.export)
        self.ui("renderModeCombo").currentTextChanged.connect(self.model.set_mode)
        self.ui("pointDisplayCombo").currentTextChanged.connect(self.contour.set_point_mode)
        self.pressure_unit.currentTextChanged.connect(self.update_pressure_unit)
        self.length_unit.currentTextChanged.connect(self.update_length_unit)

    def update_pressure_unit(self, unit):
        factor = PRESSURE_TO_MPA[unit]
        spin = self.ui("pressureSpin")
        physical_value = spin.value() * self.pressure_factor
        spin.setRange(0.01 / factor, 100 / factor)
        spin.setValue(physical_value / factor)
        spin.setSuffix(f" {unit}")
        self.pressure_factor = factor

    def update_length_unit(self, unit):
        factor = LENGTH_TO_MM[unit]
        fields = ((self.ui("altitudeSpin"), 0, 100000), (self.ui("throatSpin"), 0.1, 500),
                  (self.lip_pipe_length_spin, 0.1, 1000), (self.lip_pipe_radius_spin, 0.1, 1000),
                  (self.plug_column_length_spin, 0.1, 1000), (self.plug_column_radius_spin, 0.1, 1000),
                  (self.wall_spin, 0.01, 1000))
        for spin, minimum, maximum in fields:
            physical_value = spin.value() * self.length_factor
            spin.setRange(minimum / factor, maximum / factor)
            spin.setValue(physical_value / factor)
            spin.setSuffix(f" {unit}")
        self.length_factor = factor

    def pressure_mpa(self):
        return self.ui("pressureSpin").value() * PRESSURE_TO_MPA[self.pressure_unit.currentText()]

    def length_to_mm(self, value):
        return value * LENGTH_TO_MM[self.length_unit.currentText()]

    def calculate(self):
        inputs = AngelinoInputs(
            self.pressure_mpa(),
            self.length_to_mm(self.ui("altitudeSpin").value()) / 1000,
            self.length_to_mm(self.ui("throatSpin").value()),
            self.ui("machSpin").value(),
            self.ui("truncationSpin").value(),
            self.ui("pointSpin").value(),
            self.length_to_mm(self.lip_pipe_length_spin.value()),
            self.length_to_mm(self.lip_pipe_radius_spin.value()),
            self.length_to_mm(self.plug_column_length_spin.value()),
            self.length_to_mm(self.plug_column_radius_spin.value()),
            self.length_to_mm(self.wall_spin.value()),
        )
        try:
            result = self.calculator.calculate(inputs)
        except (ValueError, ZeroDivisionError) as error:
            QMessageBox.warning(self.window, "계산 불가", f"입력값을 확인하세요.\n{error}")
            return
        self.points = result.aerospike
        self.lip_points = result.lip
        self.lip_outer_points = [(x, radius + result.wall_thickness_mm) for x, radius in result.lip]
        self.contour.set_geometry(result.aerospike, result.lip, result.wall_thickness_mm)
        self.model.set_geometry(result.aerospike, result.lip, result.wall_thickness_mm)
        rows = [
            "Angelino 1964 approximate axisymmetric plug nozzle",
            f"design pressure ratio (p0/pa), {result.design_pressure_ratio:.5f}",
            f"design exit Mach, {result.design_exit_mach:.5f}",
            f"throat angle, {result.throat_angle_deg:.5f} deg",
            f"geometric throat area, {result.throat_area_mm2:.5f} mm^2",
            f"Lip exit radius, {result.lip_radius_mm:.5f} mm",
            "",
            "part, index, x_mm, r_mm",
        ]
        rows += [f"Lip inner, {index:03d}, {x:.5f}, {radius:.5f}" for index, (x, radius) in enumerate(self.lip_points)]
        rows += [f"Lip outer, {index:03d}, {x:.5f}, {radius:.5f}" for index, (x, radius) in enumerate(self.lip_outer_points)]
        rows += [f"Plug, {index:03d}, {x:.5f}, {radius:.5f}" for index, (x, radius) in enumerate(self.points)]
        self.ui("coordinatesText").setPlainText("\n".join(rows))
        self.ui("statusLabel").setText(
            f"✓ Tapered Lip 2개 + Plug {len(self.points)}개 좌표 생성 | Me={result.design_exit_mach:.3f}, p0/pa={result.design_pressure_ratio:.2f}"
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
