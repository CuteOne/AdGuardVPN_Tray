# settings_manager.py
from PyQt5 import QtCore

ORGANIZATION_NAME = "AdGuard"
APPLICATION_NAME = "VPNController"

def get_settings() -> QtCore.QSettings:
    """
    Returns a QSettings object configured for our application.
    """
    settings = QtCore.QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
    return settings

def load_setting(key: str, default=None):
    settings = get_settings()
    return settings.value(key, default)

def save_setting(key: str, value):
    settings = get_settings()
    settings.setValue(key, value)
