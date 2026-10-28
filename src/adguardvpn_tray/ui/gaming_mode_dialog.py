from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from adguardvpn_tray.services import gaming_mode


class GamingModeDialog(QDialog):
    def __init__(self, enabled: bool, programs: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gaming Mode")
        self.setMinimumSize(420, 480)

        intro = QLabel(
            "While any of these programs is running, the tray disconnects the VPN. "
            "It reconnects to the same location once they've all closed."
        )
        intro.setWordWrap(True)

        self._enabled_check = QCheckBox("Turn on gaming mode")
        self._enabled_check.setChecked(enabled)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.addItems(programs)

        self._running_combo = QComboBox()
        self._running_combo.setEditable(True)
        self._running_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._running_combo.addItems(gaming_mode.running_program_names())
        self._running_combo.setCurrentIndex(-1)
        self._running_combo.lineEdit().setPlaceholderText("Pick a running program…")
        add_running_button = QPushButton("Add")
        add_running_button.setAutoDefault(False)
        add_running_button.clicked.connect(lambda: self._add(self._running_combo.currentText()))

        self._pattern_field = QLineEdit()
        self._pattern_field.setPlaceholderText("…or type a name, e.g. Wow.exe or *Classic*.exe")
        self._pattern_field.returnPressed.connect(self._on_add_pattern)
        add_pattern_button = QPushButton("Add")
        add_pattern_button.setAutoDefault(False)
        add_pattern_button.clicked.connect(self._on_add_pattern)

        remove_button = QPushButton("Remove selected")
        remove_button.setAutoDefault(False)
        remove_button.clicked.connect(self._on_remove)

        running_row = QHBoxLayout()
        running_row.addWidget(self._running_combo, 1)
        running_row.addWidget(add_running_button)
        pattern_row = QHBoxLayout()
        pattern_row.addWidget(self._pattern_field, 1)
        pattern_row.addWidget(add_pattern_button)

        hint = QLabel(
            "<small>Names aren't case-sensitive, and * matches anything. Wine and Proton games "
            "show up under their .exe name. Connecting by hand during a game keeps the VPN on "
            "until that game closes.</small>"
        )
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self._enabled_check)
        layout.addSpacing(8)
        layout.addWidget(QLabel("Programs:"))
        layout.addWidget(self._list)
        layout.addLayout(running_row)
        layout.addLayout(pattern_row)
        layout.addWidget(remove_button)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def _add(self, name: str) -> None:
        name = name.strip()
        if name and name.casefold() not in {p.casefold() for p in self.programs()}:
            self._list.addItem(name)

    def _on_add_pattern(self) -> None:
        self._add(self._pattern_field.text())
        self._pattern_field.clear()

    def _on_remove(self) -> None:
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))

    def programs(self) -> list[str]:
        return [self._list.item(i).text() for i in range(self._list.count())]

    def is_enabled(self) -> bool:
        return self._enabled_check.isChecked()
