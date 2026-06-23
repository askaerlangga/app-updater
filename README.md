# App Updater

App Updater is a GTK 4 and Libadwaita desktop application for Linux designed to monitor and install package updates from multiple sources simultaneously: APT, Flatpak, Snap, and AppImage.

It is structured modularly, resource-efficient, and integrates directly with GNOME desktop notifications.

## Features

- **Unified Dashboard**: View and apply updates for APT, Flatpak, Snap, and AppImages within a single interface.
- **Dynamic Package Scanning**: Settings row options are rendered conditionally based on which package managers are actively installed on the host system.
- **System Notifications Integration**: Triggers standard `Gio.Notification` alerts with interactive action buttons when new updates are found in the background.
- **UPower Integration**: Prevents executing updates when the device is running on low battery (<25%) without a power charger connected.
- **SHA-256 Integrity Verification**: Downloads the external helper utility (`appimageupdatetool`) into a temporary file and validates its SHA-256 checksum before marking it executable.
- **Polkit Privilege Separation**: Uses graphical `pkexec` prompts to perform system-level installations for APT and Snap.

## Project Structure

The project conforms to the Single Responsibility Principle:

- `main.py`: Application entry point.
- `application.py`: Manages the GTK application lifecycle, CLI arguments, Gio Actions, and autostart registration.
- `window.py`: Controls the UI layouts, updates lists rendering, dialog flows, and the interactive terminal log panel.
- `settings.py`: Manages configuration serialization (`settings.json`) and shared update state (`state.json`).
- `updater_backend.py`: Runs update checks, manages external download routines, and executes update streams.

## Dependencies

- Python >= 3.10
- PyGObject (GTK 4, Libadwaita, Gdk, Gio, GLib)
- `python3-apt` (Python bindings for APT)
- `gir1.2-adw-1` / `libadwaita-1`
- `policykit-1` (Polkit)

## Installation

### Debian Package (.deb)

#### Method 1: Using the APT Repository (Recommended)
You can register our official APT repository to receive automatic updates:

```bash
# 1. Download the repository verification key
wget -qO- https://askaerlangga.github.io/app-updater/apt/key.gpg | gpg --dearmor | sudo tee /usr/share/keyrings/app-updater-keyring.gpg > /dev/null

# 2. Add the APT repository
echo "deb [signed-by=/usr/share/keyrings/app-updater-keyring.gpg] https://askaerlangga.github.io/app-updater/apt/ ./" | sudo tee /etc/apt/sources.list.d/app-updater.list

# 3. Update repositories and install
sudo apt update && sudo apt install app-updater
```

#### Method 2: Manual Installation
Download the latest `.deb` package from the Releases page and run:

```bash
sudo apt install ./app-updater_<version>_all.deb
```

This registers the application system-wide, generates the desktop launcher, registers the autostart daemon, and resolves the required dependencies automatically.

### Running Locally (Development)
```bash
python3 main.py
```

## CLI Usage

| Argument | Alias | Description |
|---|---|---|
| `--background` | `-b` | Starts the application in the background (scans silently, notifies if updates exist, and exits). |
| `--refresh` | `-r` | Triggers an update re-scan on the active instance. |
| `--quit` | `-q` | Exits the running main application instance. |

## Global Shortcuts
- `Ctrl + R`: Trigger update scan.
- `Ctrl + ,` (Comma): Open preferences.
- `Ctrl + U`: Update all available packages.
- `Ctrl + Q`: Quit the application.
