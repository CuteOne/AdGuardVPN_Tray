from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout


def location_key(loc) -> str:
    return f"{loc.iso}|{loc.city}"


class FavoritesDialog(QDialog):
    def __init__(self, locations, favorite_keys: set[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Favorite Locations")
        self.setMinimumSize(360, 480)

        self._filter_field = QLineEdit()
        self._filter_field.setPlaceholderText("Filter…")
        self._filter_field.textChanged.connect(self._apply_filter)

        self._list = QListWidget()
        for loc in sorted(locations, key=lambda location: (location.country, location.city)):
            item = QListWidgetItem(f"{loc.city}, {loc.country} ({loc.iso})")
            item.setData(Qt.ItemDataRole.UserRole, location_key(loc))
            item.setCheckState(
                Qt.CheckState.Checked if location_key(loc) in favorite_keys else Qt.CheckState.Unchecked
            )
            self._list.addItem(item)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._filter_field)
        layout.addWidget(self._list)
        layout.addWidget(buttons)

    def _apply_filter(self, text: str) -> None:
        text = text.lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setHidden(text not in item.text().lower())

    def selected_keys(self) -> set[str]:
        keys = set()
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                keys.add(item.data(Qt.ItemDataRole.UserRole))
        return keys
