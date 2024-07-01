"""Device simulator launcher (ARC-006, Tools menu)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from hwval_studio.simulator.server import SimulatorServer
from hwval_studio.ui.theme import COLORS, icon


class SimulatorDialog(QDialog):
    connect_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Device Simulator")
        self.resize(520, 360)
        self.server: SimulatorServer | None = None
        layout = QVBoxLayout(self)
        title = QLabel("Device simulator")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        note = QLabel(
            "The simulator implements the HWVAL, BOOT and DEMO roles over HWLINK. "
            "Use an in-process simulated device, or start a TCP server that other tools can connect to."
        )
        note.setWordWrap(True)
        note.setObjectName("Secondary")
        layout.addWidget(note)

        role_row = QHBoxLayout()
        role_row.addWidget(QLabel("Role"))
        self.role = QComboBox()
        self.role.addItems(["hwval", "boot", "demo"])
        role_row.addWidget(self.role)
        role_row.addStretch(1)
        connect = QPushButton(icon("connect", COLORS["accent"], 14), "Connect In-Process Simulator")
        connect.setObjectName("Accent")
        connect.clicked.connect(lambda: self.connect_requested.emit(f"simulator:{self.role.currentText()}"))
        role_row.addWidget(connect)
        layout.addLayout(role_row)

        server_row = QHBoxLayout()
        server_row.addWidget(QLabel("TCP server"))
        self.host = QLineEdit("127.0.0.1")
        self.host.setFixedWidth(120)
        server_row.addWidget(self.host)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(7000)
        server_row.addWidget(self.port)
        self.start_button = QPushButton("Start Server")
        self.start_button.clicked.connect(self.start_server)
        server_row.addWidget(self.start_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_server)
        server_row.addWidget(self.stop_button)
        layout.addLayout(server_row)

        self.status = QLabel("Not running")
        self.status.setObjectName("Secondary")
        layout.addWidget(self.status)

        tcp_row = QHBoxLayout()
        tcp_row.addStretch(1)
        tcp_connect = QPushButton("Connect to TCP Simulator")
        tcp_connect.clicked.connect(
            lambda: self.connect_requested.emit(f"tcp://{self.host.text().strip() or '127.0.0.1'}:{self.port.value()}")
        )
        tcp_row.addWidget(tcp_connect)
        layout.addLayout(tcp_row)
        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def start_server(self) -> None:
        if self.server is not None:
            return
        try:
            self.server = SimulatorServer(
                self.host.text().strip() or "127.0.0.1",
                self.port.value(),
                self.role.currentText(),
            )
            self.server.start()
            self.status.setText(
                f"Listening on tcp://{self.host.text().strip()}:{self.port.value()} ({self.role.currentText()})"
            )
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
        except Exception as exc:
            self.server = None
            self.status.setText(f"Could not start: {exc}")

    def stop_server(self) -> None:
        if self.server is not None:
            self.server.stop()
            self.server = None
        self.status.setText("Not running")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def closeEvent(self, event: object) -> None:
        self.stop_server()
        super().closeEvent(event)  # type: ignore[arg-type]
