"""Reusable widgets for HWVAL Studio."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from hwval_studio.protocol.codec import verdict_text
from hwval_studio.ui.theme import COLORS, icon, state_icon


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None, *, subtle: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("SubtleCard" if subtle else "Card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)


class MetricCard(Card):
    def __init__(self, title: str, value: str = "—", caption: str = "", color: str = "") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(1)
        self.title = QLabel(title)
        self.title.setObjectName("Secondary")
        self.value = QLabel(value)
        self.value.setObjectName("Metric")
        if color:
            self.value.setStyleSheet(f"color: {color};")
        self.caption = QLabel(caption)
        self.caption.setObjectName("Muted")
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.caption)

    def set_value(self, value: str, caption: str = "", color: str = "") -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"color: {color};" if color else "")
        if caption:
            self.caption.setText(caption)


class StatusPill(QWidget):
    """Result state shown by icon + word + colour (LNF-009)."""

    def __init__(self, state: str = "NOT RUN", text: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 2, 9, 2)
        layout.setSpacing(5)
        self._icon = QLabel()
        self._text = QLabel()
        self._text.setStyleSheet("font-weight: 600; font-size: 11px;")
        layout.addWidget(self._icon)
        layout.addWidget(self._text)
        self.set_state(state, text)

    def set_state(self, state: str, text: str | None = None) -> None:
        key = state.upper().replace("_", " ")
        color = COLORS.get(key.lower(), COLORS["muted"])
        if key == "N/A":
            color = COLORS["na"]
        elif key == "NOT RUN":
            color = COLORS["muted"]
        elif key == "RUNNING":
            color = COLORS["running"]
        self._icon.setPixmap(state_icon(key, 14).pixmap(14, 14))
        self._text.setText(text or key)
        self._text.setStyleSheet(f"font-weight: 700; color: {color}; font-size: 11px;")
        self.setStyleSheet(
            f"background: {color}16; border: 1px solid {color}44; border-radius: 10px;"
        )


class SearchBox(QLineEdit):
    def __init__(self, placeholder: str = "Search…", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setObjectName("SearchField")
        self.addAction(icon("search", COLORS["secondary"], 15), QLineEdit.ActionPosition.LeadingPosition)


class CountBadge(QLabel):
    def __init__(self, text: str = "", color: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_color(color)

    def set_color(self, color: str = "") -> None:
        color = color or COLORS["muted"]
        self.setStyleSheet(
            f"color: {color}; background: {color}16; border-radius: 7px; "
            "padding: 1px 6px; font-size: 10px; font-weight: 600;"
        )


class ToggleSwitch(QCheckBox):
    """A compact macOS-like toggle switch (LNF-006)."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"""
            QCheckBox {{ spacing: 8px; }}
            QCheckBox::indicator {{
                width: 30px; height: 17px; border-radius: 9px;
                background: {COLORS['separator']}; border: 1px solid {COLORS['border']};
            }}
            QCheckBox::indicator:checked {{
                background: {COLORS['accent']}; border-color: {COLORS['accent']};
            }}
            """
        )


class ActivityView(QWidget):
    """Toolbar centre: role, firmware version, state and progress (WIN-002/008)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 2, 12, 2)
        layout.setSpacing(1)
        self.title = QLabel("Not connected")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet("font-weight: 600;")
        self.detail = QLabel("Choose a port and click Connect")
        self.detail.setObjectName("Muted")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        self.progress.hide()
        layout.addWidget(self.title)
        layout.addWidget(self.detail)
        layout.addWidget(self.progress)
        self.setMinimumWidth(260)

    def set_idle(self, text: str = "Not connected", detail: str = "") -> None:
        self.title.setText(text)
        self.detail.setText(detail)
        self.progress.hide()
        self.setToolTip(detail)

    def set_busy(self, text: str, detail: str = "") -> None:
        self.title.setText(text)
        self.detail.setText(detail)
        self.progress.show()
        self.progress.setRange(0, 0)

    def set_progress(self, text: str, done: int, total: int) -> None:
        self.title.setText(text)
        percent = int(done * 100 / total) if total else 0
        self.detail.setText(f"{done:,} / {total:,} ({percent}%)")
        self.progress.show()
        self.progress.setRange(0, 100)
        self.progress.setValue(percent)

    def set_state(self, title: str, detail: str = "") -> None:
        self.title.setText(title)
        self.detail.setText(detail)
        self.progress.hide()


class EmptyState(QWidget):
    def __init__(self, text: str, icon_name: str = "chip", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glyph = QLabel()
        glyph.setPixmap(icon(icon_name, COLORS["muted"], 42).pixmap(42, 42))
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel(text)
        label.setObjectName("Muted")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(glyph)
        layout.addWidget(label)


class KeyValueGrid(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(6)
        self.grid.setColumnStretch(1, 1)
        self._rows: dict[str, QLabel] = {}

    def set_items(self, items: dict[str, Any]) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()
        for row, (key, value) in enumerate(items.items()):
            key_label = QLabel(key)
            key_label.setObjectName("Secondary")
            value_label = QLabel(str(value) if value not in (None, "") else "—")
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.grid.addWidget(key_label, row, 0)
            self.grid.addWidget(value_label, row, 1)
            self._rows[key] = value_label


class LedIndicator(QWidget):
    """On-screen LED that mirrors the board."""

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.dot = QLabel()
        self.dot.setFixedSize(18, 18)
        self.label = QLabel(name)
        self.label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.dot)
        layout.addWidget(self.label)
        self.set_pattern("OFF", 500)

    def set_pattern(self, pattern: str, period_ms: int = 500) -> None:
        colors = {
            "OFF": COLORS["separator"],
            "ON": COLORS["pass"],
            "BLINK": COLORS["pass"],
            "HEARTBEAT": COLORS["accent"],
            "FAST": COLORS["warning"],
            "CHASE": COLORS["skip"],
            "MORSE_SOS": COLORS["fail"],
        }
        color = colors.get(pattern, COLORS["muted"])
        self.dot.setStyleSheet(
            f"background: {color}; border: 1px solid {COLORS['border']}; border-radius: 9px;"
        )
        self.setToolTip(f"{pattern}, {period_ms} ms")


class ResultTableModel(QAbstractTableModel):
    """Lazy model/view table for a live run or a stored run (GNFR-003)."""

    COLUMNS = [
        ("", 24),
        ("Result", 70),
        ("ID", 82),
        ("Group", 64),
        ("Title", 250),
        ("Level", 42),
        ("Flags", 72),
        ("Duration", 70),
        ("Measured", 110),
        ("Reason / Limits", 230),
        ("Reqs", 110),
    ]

    def __init__(self, catalogue: dict[str, dict[str, Any]] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.catalogue = catalogue or {}
        self.rows: list[dict[str, Any]] = []
        self._index: dict[tuple[str, int], int] = {}

    # -- Qt model ------------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.COLUMNS):
            return self.COLUMNS[section][0]
        return section + 1

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self.rows)):
            return None
        row = self.rows[index.row()]
        column = index.column()
        meta = self.catalogue.get(str(row.get("test_id") or row.get("id")), {})
        title = row.get("title") or meta.get("title", "")
        result = verdict_text(row)
        if role == Qt.ItemDataRole.DisplayRole:
            return [
                "",
                result,
                row.get("test_id") or row.get("id", ""),
                row.get("group") or row.get("group_code", ""),
                title,
                row.get("level") or meta.get("level", ""),
                self._flags(row, meta),
                self._duration(row),
                self._measured(row),
                self._reason(row),
                row.get("reqs") or meta.get("reqs", ""),
            ][column]
        if role == Qt.ItemDataRole.DecorationRole and column == 0:
            if row.get("missing") and result == "NOT RUN":
                return icon("warning", COLORS["skip"], 16)
            return state_icon(result, 16)
        if role == Qt.ItemDataRole.ForegroundRole:
            if result == "FAIL":
                return QColor(COLORS["fail"])
            if result == "PASS":
                return QColor(COLORS["text"])
            if result in {"SKIP", "N/A"}:
                return QColor(COLORS["secondary"])
            if result == "RUNNING":
                return QColor(COLORS["accent"])
        if role == Qt.ItemDataRole.FontRole and column == 2:
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(row, meta, result)
        if role == Qt.ItemDataRole.ForegroundRole and row.get("missing") and column == 1:
            return QColor(COLORS["skip"])
        if role == Qt.ItemDataRole.UserRole:
            return row
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column in (5,):
                return int(Qt.AlignmentFlag.AlignCenter)
            if column in (7,):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    @staticmethod
    def _flags(row: dict[str, Any], meta: dict[str, Any]) -> str:
        flags = []
        if row.get("operator") if "operator" in row else meta.get("operator"):
            flags.append("OP")
        if row.get("destructive") if "destructive" in row else meta.get("destructive"):
            flags.append("DEST")
        return " ".join(flags)

    @staticmethod
    def _duration(row: dict[str, Any]) -> str:
        value = row.get("duration_ms")
        if value is None:
            return ""
        try:
            return f"{int(value)} ms"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _measured(row: dict[str, Any]) -> str:
        text = row.get("measured_text")
        if text:
            return str(text)
        measured = row.get("measured") or {}
        if isinstance(measured, dict):
            if measured.get("text"):
                return str(measured["text"])
            if measured.get("value") is not None:
                return f"{measured.get('value')} {measured.get('unit', '')}".strip()
        return str(row.get("measured") or "")

    @staticmethod
    def _reason(row: dict[str, Any]) -> str:
        reason = row.get("reason") or ""
        limits = row.get("limits_text")
        if not limits:
            limits_data = row.get("limits") or {}
            if isinstance(limits_data, dict):
                limits = limits_data.get("text", "")
        if reason and limits:
            return f"{reason} · limits {limits}"
        return str(reason or limits or "")

    @staticmethod
    def _tooltip(row: dict[str, Any], meta: dict[str, Any], result: str) -> str:
        measured = ResultTableModel._measured(row)
        limits_data = row.get("limits") if isinstance(row.get("limits"), dict) else {}
        limits = row.get("limits_text") or (limits_data or {}).get("text", "")
        lines = [
            f"{row.get('test_id') or row.get('id', '')} — {meta.get('title', row.get('title', ''))}",
            f"Result: {result}",
        ]
        if measured:
            lines.append(f"Measured: {measured}")
        if limits:
            lines.append(f"Limits: {limits}")
        if row.get("reason"):
            lines.append(f"Reason: {row['reason']}")
        if meta.get("needs"):
            lines.append(f"Needs: {meta['needs']}")
        if row.get("missing"):
            lines.append("Harness wire missing: this test is likely to be skipped")
        return "\n".join(lines)

    # -- operations ----------------------------------------------------
    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self._rebuild_index()
        self.endResetModel()

    def set_catalogue(self, catalogue: dict[str, dict[str, Any]]) -> None:
        self.catalogue = catalogue
        if self.rows:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self.rows) - 1, len(self.COLUMNS) - 1)
            )

    def update_result(self, result: dict[str, Any]) -> None:
        test_id = str(result.get("id", ""))
        iteration = int(result.get("iteration", 1))
        key = (test_id, iteration)
        row = self._index.get(key)
        if row is None:
            # A live result for an iteration that has no placeholder.
            self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows))
            self.rows.append(result)
            self._index[key] = len(self.rows) - 1
            self.endInsertRows()
            return
        self.rows[row] = {**self.rows[row], **result}
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.COLUMNS) - 1))

    def mark_running(self, test_id: str, index: int = 0, total: int = 0) -> None:
        for position, row in enumerate(self.rows):
            if str(row.get("test_id") or row.get("id")) == test_id and row.get("result") == "NOT RUN":
                row["result"] = "RUNNING"
                self.dataChanged.emit(
                    self.index(position, 0), self.index(position, len(self.COLUMNS) - 1)
                )
                break

    def mark_unfinished_not_run(self) -> None:
        changed = False
        for position, row in enumerate(self.rows):
            if str(row.get("result")) == "RUNNING":
                row["result"] = "NOT RUN"
                changed = True
                self.dataChanged.emit(
                    self.index(position, 0), self.index(position, len(self.COLUMNS) - 1)
                )
        if changed:
            self.layoutChanged.emit()

    def _rebuild_index(self) -> None:
        self._index = {}
        for position, row in enumerate(self.rows):
            self._index[(str(row.get("test_id") or row.get("id", "")), int(row.get("iteration", 1)))] = position

    def row_at(self, row: int) -> dict[str, Any] | None:
        if 0 <= row < len(self.rows):
            return self.rows[row]
        return None


class SortProxy(QSortFilterProxyModel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setDynamicSortFilter(True)
        self._query = ""
        self._result_filter = ""

    def set_query(self, query: str) -> None:
        self._query = query.strip().lower()
        self.invalidateFilter()

    def set_result_filter(self, result: str) -> None:
        self._result_filter = result.strip().upper()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if model is None:
            return True
        if self._result_filter:
            row_data = model.row_at(source_row) if hasattr(model, "row_at") else None
            if row_data is not None:
                value = verdict_text(row_data)
                if self._result_filter == "NOT RUN" and value not in {"NOT RUN", "RUNNING"}:
                    return False
                if self._result_filter != "NOT RUN" and value != self._result_filter:
                    return False
        if not self._query:
            return True
        row = model.row_at(source_row) if hasattr(model, "row_at") else None
        if row is None:
            return True
        meta = getattr(model, "catalogue", {}).get(str(row.get("test_id") or row.get("id")), {})
        haystack = " ".join(
            str(value or "")
            for value in (
                row.get("test_id"),
                row.get("id"),
                row.get("title"),
                meta.get("title"),
                row.get("group"),
                row.get("group_code"),
                row.get("reqs"),
                meta.get("reqs"),
                row.get("reason"),
            )
        ).lower()
        return self._query in haystack


class ResultTable(QTableView):
    selection_changed = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.source_model = ResultTableModel(parent=parent)
        self.proxy = SortProxy(self)
        self.proxy.setSourceModel(self.source_model)
        self.setModel(self.proxy)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(25)
        self.horizontalHeader().setStretchLastSection(True)
        for index, (_, width) in enumerate(ResultTableModel.COLUMNS):
            self.setColumnWidth(index, width)
        self.doubleClicked.connect(self._emit_selected)
        self.selectionModel().selectionChanged.connect(lambda *_: self._emit_selected())

    def _emit_selected(self, *_args: Any) -> None:
        row = self.selected_row()
        if row is not None:
            self.selection_changed.emit(row)

    def selected_row(self) -> dict[str, Any] | None:
        index = self.currentIndex()
        if not index.isValid():
            return None
        source = self.proxy.mapToSource(index)
        return self.source_model.row_at(source.row())

    def selected_rows(self) -> list[dict[str, Any]]:
        rows = []
        for index in self.selectionModel().selectedRows():
            source = self.proxy.mapToSource(index)
            row = self.source_model.row_at(source.row())
            if row:
                rows.append(row)
        return rows

    def set_query(self, query: str) -> None:
        self.proxy.set_query(query)

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self.source_model.set_rows(rows)

    def set_catalogue(self, catalogue: dict[str, dict[str, Any]]) -> None:
        self.source_model.set_catalogue(catalogue)

    def update_result(self, result: dict[str, Any]) -> None:
        self.source_model.update_result(result)
