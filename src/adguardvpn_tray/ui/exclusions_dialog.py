from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from adguardvpn_tray.parsers.exclusions_parser import EXCLUSION_MODES, entry_problem, split_entries
from adguardvpn_tray.services.exclusions import ExclusionsState

_LIST_LABELS = {
    "general": "Sites and IPs that skip the VPN:",
    "selective": "Sites and IPs that use the VPN:",
}


class ExclusionsDialog(QDialog):
    """Edits a copy of the exclusions; the caller applies the difference on accept."""

    def __init__(self, state: ExclusionsState, parent=None):
        super().__init__(parent)
        self.setWindowTitle("VPN Exceptions")
        self.setMinimumSize(420, 480)
        self._lists = {mode: list(state.lists.get(mode, [])) for mode in EXCLUSION_MODES}

        self._general_radio = QRadioButton("Use the VPN for everything except the sites below")
        self._selective_radio = QRadioButton("Use the VPN only for the sites below")
        mode_group = QButtonGroup(self)
        mode_group.addButton(self._general_radio)
        mode_group.addButton(self._selective_radio)
        (self._selective_radio if state.mode == "selective" else self._general_radio).setChecked(True)
        self._general_radio.toggled.connect(self._show_current_list)

        self._list_label = QLabel()
        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        self._entry_field = QLineEdit()
        self._entry_field.setPlaceholderText("example.com, *.example.com, 203.0.113.5 or 10.0.0.0/8")
        self._entry_field.returnPressed.connect(self._on_add)
        add_button = QPushButton("Add")
        add_button.setAutoDefault(False)
        add_button.clicked.connect(self._on_add)
        remove_button = QPushButton("Remove selected")
        remove_button.setAutoDefault(False)
        remove_button.clicked.connect(self._on_remove)

        add_row = QHBoxLayout()
        add_row.addWidget(self._entry_field)
        add_row.addWidget(add_button)

        hint = QLabel(
            "<small>A domain covers itself and its www. form. Use *.example.com for its subdomains. "
            "Each mode keeps its own list. Changes apply to an open connection straight away.</small>"
        )
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._general_radio)
        layout.addWidget(self._selective_radio)
        layout.addSpacing(8)
        layout.addWidget(self._list_label)
        layout.addWidget(self._list)
        layout.addLayout(add_row)
        layout.addWidget(remove_button)
        layout.addWidget(hint)
        layout.addWidget(buttons)

        self._show_current_list()

    def _current_mode(self) -> str:
        return "general" if self._general_radio.isChecked() else "selective"

    def _show_current_list(self) -> None:
        mode = self._current_mode()
        self._list_label.setText(_LIST_LABELS[mode])
        self._list.clear()
        self._list.addItems(self._lists[mode])

    def _on_add(self) -> None:
        entries = split_entries(self._entry_field.text())
        problems = [p for p in (entry_problem(e) for e in entries) if p]
        if problems:
            QMessageBox.warning(self, "Can't add", "\n".join(problems))
            return
        current = self._lists[self._current_mode()]
        for entry in entries:
            if entry not in current:
                current.append(entry)
        self._entry_field.clear()
        self._show_current_list()

    def _on_remove(self) -> None:
        selected = {item.text() for item in self._list.selectedItems()}
        mode = self._current_mode()
        self._lists[mode] = [entry for entry in self._lists[mode] if entry not in selected]
        self._show_current_list()

    def result_state(self) -> ExclusionsState:
        return ExclusionsState(mode=self._current_mode(), lists={m: list(v) for m, v in self._lists.items()})
