from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from adguardvpn_tray.adapters.cli_adapter import CliAdapter
from adguardvpn_tray.config.app_config import AppConfig
from adguardvpn_tray.parsers.ansi import strip_ansi
from adguardvpn_tray.services import error_reporter


class SettingsDialog(QDialog):
    def __init__(
        self, config: AppConfig, cli: CliAdapter, on_refresh_interval_changed=None, show_diagnostics=False, parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("Advanced Settings")
        self.setMinimumWidth(480)
        self._config = config
        self._cli = cli
        self._on_refresh_interval_changed = on_refresh_interval_changed

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "General")
        tabs.addTab(self._build_config_tab(), "CLI Configuration")
        diagnostics_index = tabs.addTab(self._build_diagnostics_tab(), "Diagnostics")
        tabs.addTab(self._build_exclusions_tab(), "Site Exclusions")
        if show_diagnostics:
            tabs.setCurrentIndex(diagnostics_index)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _build_general_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        self._refresh_spin = QSpinBox()
        self._refresh_spin.setRange(2, 60)
        self._refresh_spin.setSuffix(" s")
        self._refresh_spin.setValue(self._config.refresh_interval_s)
        self._refresh_spin.valueChanged.connect(self._on_refresh_changed)
        form.addRow("Status refresh interval", self._refresh_spin)

        self._binary_path_field = QLineEdit(self._config.binary_path_override or self._cli.binary_path)
        self._binary_path_field.editingFinished.connect(self._on_binary_path_changed)
        form.addRow("CLI binary path", self._binary_path_field)

        return widget

    def _build_config_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        text = QPlainTextEdit()
        text.setReadOnly(True)

        result = self._cli.config_show()
        text.setPlainText(strip_ansi(result.stdout) or "Unable to read configuration.")
        layout.addWidget(text)
        return widget

    def _build_diagnostics_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self._error_log_text = QPlainTextEdit()
        self._error_log_text.setReadOnly(True)
        self._reload_error_log()
        layout.addWidget(self._error_log_text)

        buttons = QHBoxLayout()
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._reload_error_log)
        clear_button = QPushButton("Clear Log")
        clear_button.clicked.connect(self._on_clear_error_log)
        buttons.addWidget(refresh_button)
        buttons.addWidget(clear_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        return widget

    def _reload_error_log(self) -> None:
        content = error_reporter.read_log()
        self._error_log_text.setPlainText(content or "No errors recorded.")

    def _on_clear_error_log(self) -> None:
        error_reporter.clear_log()
        self._reload_error_log()

    def _build_exclusions_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel("Site exclusions (split tunneling) management is coming in a future version.")
        label.setWordWrap(True)
        label.setEnabled(False)
        layout.addWidget(label)
        return widget

    def _on_refresh_changed(self, value: int) -> None:
        self._config.refresh_interval_s = value
        self._config.save()
        if self._on_refresh_interval_changed:
            self._on_refresh_interval_changed(value)

    def _on_binary_path_changed(self) -> None:
        path = self._binary_path_field.text().strip()
        self._config.binary_path_override = path or None
        self._config.save()
        if path:
            self._cli.binary_path = path
