from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from adguardvpn_tray.services import error_reporter
from adguardvpn_tray.services.login_service import LoginService


class LoginDialog(QDialog):
    def __init__(self, binary_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Log in to AdGuard VPN")
        self.setMinimumWidth(420)

        self._status_label = QLabel("Starting login…")
        self._status_label.setWordWrap(True)

        self._url_field = QLineEdit()
        self._url_field.setReadOnly(True)
        self._url_field.setVisible(False)

        self._copy_button = QPushButton("Copy Link")
        self._copy_button.setVisible(False)
        self._copy_button.clicked.connect(self._copy_url)

        self._open_button = QPushButton("Open in Browser")
        self._open_button.setVisible(False)
        self._open_button.clicked.connect(self._open_url)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._buttons.rejected.connect(self._on_cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(self._status_label)
        layout.addWidget(self._url_field)
        layout.addWidget(self._open_button)
        layout.addWidget(self._copy_button)
        layout.addWidget(self._buttons)

        self._url = ""
        self._succeeded = False

        self._service = LoginService(binary_path)
        self._service.menu_ready.connect(self._on_menu_ready)
        self._service.url_ready.connect(self._on_url_ready)
        self._service.succeeded.connect(self._on_succeeded)
        self._service.failed.connect(self._on_failed)
        self._service.timed_out.connect(self._on_timed_out)
        self._service.cancelled.connect(self._on_cancelled)
        self._service.start()

    def _on_menu_ready(self) -> None:
        self._status_label.setText("Requesting a sign-in link…")

    def _on_url_ready(self, url: str) -> None:
        self._url = url
        self._status_label.setText(
            "Complete sign-in in your browser (email, password, and any 2FA "
            "happen on AdGuard's site, not here). Waiting for confirmation…"
        )
        self._url_field.setText(url)
        self._url_field.setVisible(True)
        self._copy_button.setVisible(True)
        self._open_button.setVisible(True)
        QDesktopServices.openUrl(QUrl(url))

    def _on_succeeded(self) -> None:
        self._succeeded = True
        self._status_label.setText("Successfully logged in.")
        self._buttons.clear()
        self._buttons.addButton(QDialogButtonBox.StandardButton.Ok)
        self._buttons.accepted.connect(self.accept)

    def _on_failed(self, message: str) -> None:
        self._status_label.setText(f"Login failed: {message.strip() or 'unknown error'}")
        error_reporter.report_error("login_failed", message)
        self._buttons.clear()
        self._buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self._buttons.rejected.connect(self.reject)

    def _on_timed_out(self) -> None:
        self._status_label.setText("Login timed out waiting for browser confirmation.")
        error_reporter.report_error("login_timeout", "Login timed out waiting for browser confirmation.")
        self._buttons.clear()
        self._buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self._buttons.rejected.connect(self.reject)

    def _on_cancelled(self) -> None:
        self.reject()

    def _on_cancel(self) -> None:
        self._service.cancel()
        self.reject()

    def _copy_url(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._url)

    def _open_url(self) -> None:
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if not self._succeeded:
            self._service.cancel()
        super().closeEvent(event)

    @property
    def succeeded(self) -> bool:
        return self._succeeded
