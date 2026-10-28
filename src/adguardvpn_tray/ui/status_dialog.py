from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from adguardvpn_tray.services import status_report
from adguardvpn_tray.services.status_report import StatusSnapshot


class StatusDetailsDialog(QDialog):
    """Live view of the current state - refreshed by the tray on every status poll."""

    def __init__(self, on_open_diagnostics: Callable[[], None], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Status details")
        self.setMinimumWidth(460)
        self._copy_text = ""

        self._form = QFormLayout()
        self._form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        note = QLabel(status_report.DIAGNOSTICS_NOTE)
        note.setWordWrap(True)
        open_diagnostics = QPushButton("Open Diagnostics…")
        open_diagnostics.clicked.connect(on_open_diagnostics)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy_button = buttons.addButton("Copy", QDialogButtonBox.ButtonRole.ActionRole)
        copy_button.setToolTip("Copy these details as text (your account email is left out)")
        copy_button.clicked.connect(self._copy)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(self._form)
        layout.addSpacing(8)
        layout.addWidget(note)
        layout.addWidget(open_diagnostics, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(buttons)

    def update_snapshot(self, snapshot: StatusSnapshot) -> None:
        # Rows come and go with the state (Location etc. only while connected), so rebuild.
        while self._form.rowCount():
            self._form.removeRow(0)
        for label, value in status_report.detail_rows(snapshot):
            field = QLabel(value)
            field.setWordWrap(True)
            field.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._form.addRow(f"{label}:", field)
        self._copy_text = status_report.as_text(status_report.detail_rows(snapshot, include_email=False))

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._copy_text)
