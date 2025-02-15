#!/bin/bash

APP_NAME="adguardvpn_tray"
VENV_DIR="venv"
DIST_DIR="dist"
APPDIR="AppDir"

echo "🚀 Setting up environment and building AdGuard VPN Tray..."

# 1️⃣ Ensure dependencies
sudo dnf install python3 python3-qt5 qt5-qtbase-devel xdg-utils -y

# 2️⃣ Create virtual environment
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install pyqt5 pyinstaller

# 3️⃣ Build using PyInstaller
pyinstaller --onefile --windowed --name "$APP_NAME" --add-data "resources/icons:resources/icons" main.py

# 4️⃣ Prepare AppDir structure
mkdir -p "$APPDIR/usr/bin"
cp "$DIST_DIR/$APP_NAME" "$APPDIR/usr/bin/"

# Copy external icon for the desktop launcher
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp "resources/icons/Connected.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/${APP_NAME}.png"

mkdir -p "$APPDIR/usr/share/applications"
cat > "$APPDIR/usr/share/applications/$APP_NAME.desktop" <<EOL
[Desktop Entry]
Name=AdGuard VPN Tray
Exec=$APP_NAME
Icon=$APP_NAME
Terminal=false
Type=Application
Categories=Network;
EOL

# 5️⃣ Build AppImage
echo "📦 Creating AppImage..."
appimagetool "$APPDIR" "${APP_NAME}.AppImage"

echo "✅ Build complete! Run your AppImage with:"
echo "./${APP_NAME}.AppImage"
