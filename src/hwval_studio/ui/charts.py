"""Small painted charts for the run history (no plotting dependency).

Author: Sandesh Ghimire <sandesh@soccentric.com>
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from hwval_studio.ui.theme import COLORS

_MAX_BARS = 40


@dataclass(frozen=True)
class RunPoint:
    """One run as a bar: counts per result, plus a short axis label."""

    label: str
    n_pass: int
    n_fail: int
    n_skip: int
    n_na: int = 0

    @property
    def total(self) -> int:
        return self.n_pass + self.n_fail + self.n_skip + self.n_na

    @property
    def decided(self) -> int:
        """Tests that gave a verdict; SKIP and N/A do not count against the rate."""
        return self.n_pass + self.n_fail

    @property
    def pass_rate(self) -> float | None:
        return None if self.decided == 0 else 100.0 * self.n_pass / self.decided


def points_from_runs(runs: Sequence[dict[str, object]]) -> list[RunPoint]:
    """History rows (newest first, as the store lists them) to oldest-first points."""
    points: list[RunPoint] = []
    for run in reversed(list(runs)):
        started = str(run.get("started_at") or "")
        label = started[5:16].replace("T", " ") if len(started) >= 16 else started

        def count(key: str, run: dict[str, object] = run) -> int:
            value = run.get(key) or 0
            return int(value) if isinstance(value, int | float | str) and str(value).isdigit() else 0

        points.append(
            RunPoint(label, count("n_pass"), count("n_fail"), count("n_skip"), count("n_na"))
        )
    return points[-_MAX_BARS:]


class RunTrendChart(QWidget):
    """Stacked PASS / FAIL / SKIP bars per run with the pass rate drawn over them."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points: list[RunPoint] = []
        self.setMinimumHeight(170)
        self.setMaximumHeight(210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_points(self, points: Sequence[RunPoint]) -> None:
        self._points = list(points)[-_MAX_BARS:]
        self.update()

    def points(self) -> list[RunPoint]:
        return list(self._points)

    # -- painting ---------------------------------------------------------
    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = QFont(self.font())
        font.setPointSizeF(max(7.5, font.pointSizeF() - 1.5))
        painter.setFont(font)
        text = QColor(COLORS["secondary"])
        grid = QColor(COLORS["border"])

        left, right, top, bottom = 34.0, 40.0, 22.0, 20.0
        area = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)

        self._legend(painter, text)
        if not self._points:
            painter.setPen(text)
            painter.drawText(
                QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, "No runs in this range"
            )
            return

        peak = max(1, max(point.total for point in self._points))
        # Rate axis on the right, count axis on the left, four gridlines.
        for step in range(5):
            y = area.bottom() - area.height() * step / 4
            painter.setPen(QPen(grid, 1))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(text)
            painter.drawText(
                QRectF(0, y - 8, left - 6, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                str(round(peak * step / 4)),
            )
            painter.drawText(
                QRectF(area.right() + 6, y - 8, right - 6, 16),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{25 * step}%",
            )

        slot = area.width() / len(self._points)
        bar = max(3.0, min(28.0, slot * 0.64))
        painter.setPen(Qt.PenStyle.NoPen)
        rate_path = QPainterPath()
        rate_dots: list[QPointF] = []
        started = False
        for index, point in enumerate(self._points):
            x = area.left() + slot * index + (slot - bar) / 2
            floor = area.bottom()
            for count, key in (
                (point.n_pass, "pass"),
                (point.n_fail, "fail"),
                (point.n_skip + point.n_na, "skip"),
            ):
                if count <= 0:
                    continue
                height = area.height() * count / peak
                painter.setBrush(QColor(COLORS[key]))
                painter.drawRoundedRect(QRectF(x, floor - height, bar, height), 2, 2)
                floor -= height
            rate = point.pass_rate
            if rate is not None:
                spot = QPointF(x + bar / 2, area.bottom() - area.height() * rate / 100)
                rate_dots.append(spot)
                if started:
                    rate_path.lineTo(spot)
                else:
                    rate_path.moveTo(spot)
                    started = True

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(COLORS["accent"]), 2))
        painter.drawPath(rate_path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["accent"]))
        for spot in rate_dots:
            painter.drawEllipse(spot, 3.0, 3.0)

        # First and last run labels keep the axis readable at any width.
        painter.setPen(text)
        painter.drawText(
            QRectF(area.left(), area.bottom() + 3, area.width() / 2, 14),
            Qt.AlignmentFlag.AlignLeft,
            self._points[0].label,
        )
        if len(self._points) > 1:
            painter.drawText(
                QRectF(area.center().x(), area.bottom() + 3, area.width() / 2, 14),
                Qt.AlignmentFlag.AlignRight,
                self._points[-1].label,
            )

    def _legend(self, painter: QPainter, text: QColor) -> None:
        x = 34.0
        for label, key in (
            ("PASS", "pass"),
            ("FAIL", "fail"),
            ("SKIP / N/A", "skip"),
            ("Pass rate", "accent"),
        ):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS[key]))
            painter.drawRoundedRect(QRectF(x, 5, 9, 9), 2, 2)
            painter.setPen(text)
            width = painter.fontMetrics().horizontalAdvance(label)
            painter.drawText(QRectF(x + 14, 2, width + 4, 15), Qt.AlignmentFlag.AlignVCenter, label)
            x += 14 + width + 18
