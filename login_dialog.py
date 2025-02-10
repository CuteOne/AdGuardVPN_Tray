# login_dialog.py
from PyQt5 import QtWidgets

class LoginDialog(QtWidgets.QDialog):
    """
    Custom dialog for entering username and password.
    """
    def __init__(self, parent=None):
        super(LoginDialog, self).__init__(parent)
        self.setWindowTitle("AdGuard VPN Login")
        self.resize(300, 100)
        self.username = None
        self.password = None

        layout = QtWidgets.QFormLayout(self)

        self.username_edit = QtWidgets.QLineEdit(self)
        self.password_edit = QtWidgets.QLineEdit(self)
        self.password_edit.setEchoMode(QtWidgets.QLineEdit.Password)

        layout.addRow("Username:", self.username_edit)
        layout.addRow("Password:", self.password_edit)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def accept(self):
        self.username = self.username_edit.text().strip()
        self.password = self.password_edit.text().strip()
        if not self.username or not self.password:
            QtWidgets.QMessageBox.warning(self, "Input Error", "Both username and password are required.")
            return
        super(LoginDialog, self).accept()
