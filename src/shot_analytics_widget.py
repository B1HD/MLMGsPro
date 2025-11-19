import math
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.ball_data import BallData


class MetricBlock(QFrame):
    """Simple panel used for the large headline metrics."""

    def __init__(self, title: str, unit: str = "", decimals: int = 1) -> None:
        super().__init__()
        self.unit = unit
        self.decimals = decimals
        self._base_style = (
            "QFrame {"
            "background-color: #11161c;"
            "border: 1px solid #2f3842;"
            "border-radius: 8px;"
            "}"
        )
        self._highlight_style = (
            "QFrame {"
            "background-color: #1f2d36;"
            "border: 1px solid #40c4ff;"
            "border-radius: 8px;"
            "}"
        )
        self.setStyleSheet(self._base_style)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        title_label = QLabel(title.upper())
        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #9fb3c8; letter-spacing: 1px;")
        layout.addWidget(title_label, alignment=Qt.AlignLeft)

        self.value_label = QLabel("--")
        value_font = QFont()
        value_font.setPointSize(28)
        value_font.setBold(True)
        self.value_label.setFont(value_font)
        self.value_label.setStyleSheet("color: #f7f9fb;")
        layout.addWidget(self.value_label, alignment=Qt.AlignLeft)

    def set_value(self, value: Optional[float], highlight: bool = False) -> None:
        if value is None:
            text = "--"
        else:
            text = f"{value:.{self.decimals}f}"
            if self.unit:
                text = f"{text} {self.unit}"
        self.value_label.setText(text)
        self.setStyleSheet(self._highlight_style if highlight else self._base_style)

    def reset(self) -> None:
        self.set_value(None)


class DetailSection(QFrame):
    """Displays label/value pairs for the more granular shot metrics."""

    def __init__(self, title: str, metrics: Dict[str, str]) -> None:
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame {"
            "background-color: #0f151c;"
            "border: 1px solid #2a323d;"
            "border-radius: 8px;"
            "}"
        )
        self._value_style = "color: #f0f4f8; font-size: 18px; font-weight: 600;"
        self._highlight_style = (
            "color: #7ae2ff; font-size: 18px; font-weight: 700;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QLabel(title)
        header_font = QFont()
        header_font.setPointSize(12)
        header_font.setBold(True)
        header.setFont(header_font)
        header.setStyleSheet("color: #9fb3c8; letter-spacing: 0.5px;")
        layout.addWidget(header)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(6)
        layout.addLayout(self.grid)

        self._value_labels: Dict[str, QLabel] = {}
        row = 0
        for metric_key, metric_name in metrics.items():
            label = QLabel(metric_name)
            label.setStyleSheet("color: #7c8b9c; font-size: 12px;")
            self.grid.addWidget(label, row, 0, alignment=Qt.AlignLeft)

            value_label = QLabel("--")
            value_label.setStyleSheet(self._value_style)
            self.grid.addWidget(value_label, row, 1, alignment=Qt.AlignRight)
            self._value_labels[metric_key] = value_label
            row += 1

    def set_value(self, key: str, text: str, highlight: bool = False) -> None:
        if key not in self._value_labels:
            return
        label = self._value_labels[key]
        label.setText(text)
        label.setStyleSheet(
            self._highlight_style if highlight else self._value_style
        )

    def reset(self) -> None:
        for label in self._value_labels.values():
            label.setText("--")
            label.setStyleSheet(self._value_style)


class ShotAnalyticsWidget(QWidget):
    """Graphical analytics panel for displaying ball/club metrics."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tracked_metrics = (
            "speed",
            "club_speed",
            "efficiency",
            "speed_at_impact",
            "total_spin",
            "face_to_path",
            "face_to_target",
            "path",
            "angle_of_attack",
            "hla",
            "vla",
            "spin_axis",
            "back_spin",
            "side_spin",
        )
        self._last_values: Dict[str, Optional[float]] = {
            key: None for key in self._tracked_metrics
        }
        self._build_ui()
        self.reset()

    def _build_ui(self) -> None:
        self.setObjectName("ShotAnalyticsWidget")
        self.setStyleSheet("background-color: #050709;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        self.status_label = QLabel("Waiting for shot data")
        status_font = QFont()
        status_font.setPointSize(12)
        status_font.setBold(True)
        self.status_label.setFont(status_font)
        self.status_label.setStyleSheet("color: #9fb3c8;")
        header_row.addWidget(self.status_label, 1)

        self.club_label = QLabel("Club: --")
        club_font = QFont()
        club_font.setPointSize(12)
        club_font.setBold(True)
        self.club_label.setFont(club_font)
        self.club_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.club_label.setStyleSheet(
            "color: #f7f9fb; background-color: #1b2530;"
            "border: 1px solid #2c3844; border-radius: 6px; padding: 6px 12px;"
        )
        header_row.addWidget(self.club_label, 0)
        layout.addLayout(header_row)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(12)
        self.summary_blocks = {
            "speed": MetricBlock("Ball Speed", "mph", 1),
            "club_speed": MetricBlock("Club Speed", "mph", 1),
            "efficiency": MetricBlock("Efficiency", "", 2),
            "speed_at_impact": MetricBlock("Speed @ Impact", "mph", 1),
            "total_spin": MetricBlock("Spin Rate", "rpm", 0),
        }
        for block in self.summary_blocks.values():
            summary_row.addWidget(block, 1)
        layout.addLayout(summary_row)

        details_row = QHBoxLayout()
        details_row.setSpacing(12)

        self.face_section = DetailSection(
            "Face Relationship",
            {
                "face_to_path": "Face to Path",
                "face_to_target": "Face to Target",
                "path": "Club Path",
                "angle_of_attack": "Angle of Attack",
            },
        )
        details_row.addWidget(self.face_section, 1)

        self.launch_section = DetailSection(
            "Launch",
            {
                "hla": "Launch Direction (HLA)",
                "vla": "Launch Angle (VLA)",
                "spin_axis": "Spin Axis",
            },
        )
        details_row.addWidget(self.launch_section, 1)

        self.spin_section = DetailSection(
            "Spin",
            {
                "back_spin": "Back Spin",
                "side_spin": "Side Spin",
            },
        )
        details_row.addWidget(self.spin_section, 1)

        layout.addLayout(details_row)

    def reset(self) -> None:
        for block in self.summary_blocks.values():
            block.reset()
        self.face_section.reset()
        self.launch_section.reset()
        self.spin_section.reset()
        self.status_label.setText("Waiting for shot data")
        self.status_label.setStyleSheet("color: #9fb3c8;")
        self.club_label.setText("Club: --")
        for key in self._tracked_metrics:
            self._last_values[key] = None

    def update_metrics(self, balldata: Optional[BallData], partial_update: bool = False) -> None:
        if balldata is None:
            self.reset()
            return

        self.club_label.setText(f"Club: {balldata.club or '--'}")
        if partial_update:
            self.status_label.setText("Partial metrics update received")
            self.status_label.setStyleSheet("color: #f5c04a;")
        else:
            self.status_label.setText("Shot data updated")
            self.status_label.setStyleSheet("color: #7fe36c;")

        values = self._prepare_values(balldata)
        for metric, value in values.items():
            changed = value != self._last_values.get(metric)
            highlight = partial_update and changed
            if metric in self.summary_blocks:
                self.summary_blocks[metric].set_value(value, highlight)
            elif metric in ("face_to_path", "face_to_target", "path", "angle_of_attack"):
                text = self._format_directional_text(metric, value)
                self.face_section.set_value(metric, text, highlight)
            elif metric in ("hla", "vla", "spin_axis"):
                text = self._format_directional_text(metric, value)
                self.launch_section.set_value(metric, text, highlight)
            elif metric in ("back_spin", "side_spin"):
                text = self._format_spin(value)
                self.spin_section.set_value(metric, text, highlight)
            self._last_values[metric] = value

    def _prepare_values(self, balldata: BallData) -> Dict[str, Optional[float]]:
        values: Dict[str, Optional[float]] = {}
        values["speed"] = self._valid_value(balldata.speed)
        values["club_speed"] = self._valid_value(balldata.club_speed)
        values["efficiency"] = self._calc_efficiency(
            values["speed"], values["club_speed"]
        )
        values["speed_at_impact"] = self._valid_value(balldata.speed_at_impact)
        values["total_spin"] = self._valid_value(balldata.total_spin)
        values["face_to_path"] = self._valid_value(balldata.face_to_path)
        values["face_to_target"] = self._valid_value(balldata.face_to_target)
        values["path"] = self._valid_value(balldata.path)
        values["angle_of_attack"] = self._valid_value(balldata.angle_of_attack)
        values["hla"] = self._valid_value(balldata.hla)
        values["vla"] = self._valid_value(balldata.vla)
        values["spin_axis"] = self._valid_value(balldata.spin_axis)
        values["back_spin"] = self._valid_value(balldata.back_spin)
        values["side_spin"] = self._valid_value(balldata.side_spin)
        return values

    def _valid_value(self, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)) and value != BallData.invalid_value:
            return value
        return None

    def _calc_efficiency(
        self, ball_speed: Optional[float], club_speed: Optional[float]
    ) -> Optional[float]:
        if not ball_speed or not club_speed or club_speed == 0:
            return None
        return round(ball_speed / club_speed, 2)

    def _format_directional_text(
        self, metric: str, value: Optional[float]
    ) -> str:
        if value is None:
            return "--"
        magnitude = abs(value)
        if metric == "face_to_path":
            return self._format_directional_value(
                magnitude,
                value,
                neutral="Square",
                pos_label="Open",
                neg_label="Closed",
            )
        if metric == "face_to_target":
            return self._format_directional_value(
                magnitude,
                value,
                neutral="Square",
                pos_label="Open",
                neg_label="Closed",
            )
        if metric == "path":
            return self._format_directional_value(
                magnitude,
                value,
                neutral="Zero",
                pos_label="InToOut",
                neg_label="OutToIn",
            )
        if metric == "angle_of_attack":
            return self._format_directional_value(
                magnitude,
                value,
                neutral="Level",
                pos_label="Up",
                neg_label="Down",
            )
        if metric == "hla":
            return self._format_directional_value(
                magnitude,
                value,
                neutral="Center",
                pos_label="Right",
                neg_label="Left",
            )
        if metric == "vla":
            return f"{magnitude:.1f}°"
        if metric == "spin_axis":
            return self._format_directional_value(
                magnitude,
                value,
                neutral="Zero",
                pos_label="Right",
                neg_label="Left",
            )
        return f"{magnitude:.1f}"

    def _format_directional_value(
        self,
        magnitude: float,
        raw_value: float,
        neutral: str,
        pos_label: str,
        neg_label: str,
    ) -> str:
        if math.isclose(magnitude, 0.0, abs_tol=0.05):
            return neutral
        direction = pos_label if raw_value > 0 else neg_label
        return f"{magnitude:.1f}° {direction}"

    def _format_spin(self, value: Optional[float]) -> str:
        if value is None:
            return "--"
        return f"{value:.0f} rpm"
