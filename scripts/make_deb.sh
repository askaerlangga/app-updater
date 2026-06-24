#!/bin/bash
# Script to build Debian package (.deb) for App Updater dynamically
set -e

BUILD_DIR="/tmp/app-updater-build"
VERSION="${1:-1.1.0}"
# Get the version without leading 'v' if present (e.g., v1.0.0 -> 1.0.0)
VERSION="${VERSION#v}"
DEB_NAME="app-updater_${VERSION}_all.deb"
# Get the root directory of the project (parent of the scripts/ folder)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Creating build directory structure..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/DEBIAN"
mkdir -p "$BUILD_DIR/usr/bin"
mkdir -p "$BUILD_DIR/usr/share/app-updater"
mkdir -p "$BUILD_DIR/usr/share/applications"

# 1. Create control file
echo "Writing DEBIAN/control..."
cat << EOF > "$BUILD_DIR/DEBIAN/control"
Package: app-updater
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: all
Depends: python3, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, python3-apt, policykit-1
Maintainer: Aska <aska@localhost>
Description: Graphical package updater for APT, Flatpak, Snap, and AppImage.
 A native GTK 4 and Libadwaita desktop application that monitors and installs
 system packages, Flatpaks, Snaps, and AppImages in a unified dashboard.
EOF

# 2. Create postinst script
echo "Writing DEBIAN/postinst..."
cat << 'EOF' > "$BUILD_DIR/DEBIAN/postinst"
#!/bin/sh
set -e

# Make files executable
chmod +x /usr/bin/app-updater
chmod +x /usr/share/app-updater/main.py

# Update desktop application database
if [ -x "$(command -v update-desktop-database)" ]; then
    update-desktop-database -q || true
fi

echo "App Updater has been successfully installed!"
exit 0
EOF
chmod 755 "$BUILD_DIR/DEBIAN/postinst"

# 3. Create wrapper script in usr/bin
echo "Writing wrapper script..."
cat << 'EOF' > "$BUILD_DIR/usr/bin/app-updater"
#!/bin/bash
exec python3 /usr/share/app-updater/main.py "$@"
EOF
chmod +x "$BUILD_DIR/usr/bin/app-updater"

# 4. Create global desktop entry file
echo "Writing desktop entry..."
cat << 'EOF' > "$BUILD_DIR/usr/share/applications/com.aska.app_updater.desktop"
[Desktop Entry]
Name=App Updater
Comment=Update system packages, Flatpaks, Snaps, and AppImages
Exec=/usr/bin/app-updater
Icon=system-software-update
Terminal=false
Type=Application
Categories=System;Settings;
StartupNotify=true
X-GNOME-Autostart-enabled=true
EOF

# 5. Copy source code files
echo "Copying source files..."
cp -v "$PROJECT_DIR/main.py" "$BUILD_DIR/usr/share/app-updater/"
cp -v "$PROJECT_DIR/settings.py" "$BUILD_DIR/usr/share/app-updater/"
cp -v "$PROJECT_DIR/window.py" "$BUILD_DIR/usr/share/app-updater/"
cp -v "$PROJECT_DIR/application.py" "$BUILD_DIR/usr/share/app-updater/"
cp -v "$PROJECT_DIR/updater_backend.py" "$BUILD_DIR/usr/share/app-updater/"

# 5b. Copy bundled external binaries if present
if [ -f "$PROJECT_DIR/bin/appimageupdatetool" ]; then
    echo "Bundling appimageupdatetool into /usr/bin..."
    cp -v "$PROJECT_DIR/bin/appimageupdatetool" "$BUILD_DIR/usr/bin/appimageupdatetool"
    chmod +x "$BUILD_DIR/usr/bin/appimageupdatetool"
fi

# 6. Build Debian package
echo "Building Debian package (.deb)..."
dpkg-deb --build "$BUILD_DIR" "$PROJECT_DIR/$DEB_NAME"

echo "Cleaning up build files..."
rm -rf "$BUILD_DIR"

echo "Debian package successfully built at $PROJECT_DIR/$DEB_NAME"
