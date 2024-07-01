"""Small shared building blocks for the content pages."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from hwval_studio.ui.theme import COLORS, icon
from hwval_studio.ui.widgets import Card


class Page(QWidget):
    def __init__(self, title: str, subtitle: str = "", icon_name: str = "chip", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 14, 18, 12)
        self.layout.setSpacing(10)
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        glyph = QLabel()
        glyph.setPixmap(icon(icon_name, COLORS["accent"], 26).pixmap(26, 26))
        header_layout.addWidget(glyph)
        text_box = QVBoxLayout()
        text_box.setSpacing(0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("PageTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("Secondary")
        text_box.addWidget(self.title_label)
        text_box.addWidget(self.subtitle_label)
        header_layout.addLayout(text_box)
        header_layout.addStretch(1)
        self.header_actions = QHBoxLayout()
        self.header_actions.setSpacing(6)
        header_layout.addLayout(self.header_actions)
        self.layout.addWidget(header)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        self.layout.addLayout(self.body, 1)

    def add_action(self, widget: QWidget) -> None:
        self.header_actions.addWidget(widget)

    def set_title(self, title: str, subtitle: str | None = None) -> None:
        self.title_label.setText(title)
        if subtitle is not None:
            self.subtitle_label.setText(subtitle)


class ScrollPage(Page):
    def __init__(self, title: str, subtitle: str = "", icon_name: str = "chip", parent: QWidget | None = None) -> None:
        super().__init__(title, subtitle, icon_name, parent)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 6, 0)
        self.content_layout.setSpacing(10)
        self.scroll.setWidget(self.content)
        self.body.addWidget(self.scroll, 1)

    def add_card(self, card: QWidget) -> None:
        self.content_layout.addWidget(card)

    def add_stretch(self) -> None:
        self.content_layout.addStretch(1)


class SectionCard(Card):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 11, 14, 12)
        self.layout.setSpacing(7)
        header = QHBoxLayout()
        header.setSpacing(8)
        self.title = QLabel(title)
        self.title.setObjectName("Heading")
        header.addWidget(self.title)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("Muted")
            header.addWidget(subtitle_label)
        header.addStretch(1)
        self.header = header
        self.layout.addLayout(header)
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        self.layout.addLayout(self.body)

    def add_widget(self, widget: QWidget) -> None:
        self.body.addWidget(widget)

    def add_layout(self, layout: QHBoxLayout | QVBoxLayout) -> None:
        self.body.addLayout(layout)


class StatRow(QWidget):
    def __init__(self, items: list[tuple[str, str]] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QGridLayout

        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        self.cards: dict[str, tuple[QLabel, QLabel]] = {}
        if items:
            self.set_items(items)

    def set_items(self, items: list[tuple[str, str]]) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.cards.clear()
        for index, (label, value) in enumerate(items):
            card = Card(subtle=True)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(11, 7, 11, 7)
            layout.setSpacing(0)
            title = QLabel(label)
            title.setObjectName("Muted")
            title.setStyleSheet("font-size: 10px;")
            text = QLabel(value)
            text.setStyleSheet("font-size: 16px; font-weight: 700;")
            layout.addWidget(title)
            layout.addWidget(text)
            self.grid.addWidget(card, 0, index)
            self.cards[label] = (title, text)

    def set_value(self, label: str, value: str, color: str = "") -> None:
        if label in self.cards:
            text = self.cards[label][1]
            text.setText(value)
            text.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {color};" if color else "font-size: 16px; font-weight: 700;")


class Banner(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setWordWrap(True)
        self.hide()

    def show_message(self, text: str, *, error: bool = False) -> None:
        self.setText(text)
        if error:
            self.setStyleSheet(
                f"background: {COLORS['fail_soft']}; border: 1px solid {COLORS['fail']}55; "
                f"border-radius: 8px; padding: 7px 11px; color: {COLORS['text']};"
            )
        else:
            self.setStyleSheet("")
            self.setObjectName("Banner")
        self.show()


class EmptyPage(Page):
    def __init__(self, title: str, message: str, icon_name: str = "chip", parent: QWidget | None = None) -> None:
        super().__init__(title, "", icon_name, parent)
        from hwval_studio.ui.widgets import EmptyState

        self.body.addWidget(EmptyState(message, icon_name), 1)
