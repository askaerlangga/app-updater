import sys
import os
import subprocess
from typing import Any
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import GLib, Gio, Adw

from window import AppUpdaterWindow

class AppUpdater(Adw.Application):
    """Application lifecycle and command-line manager for App Updater."""
    
    def __init__(self) -> None:
        super().__init__(
            application_id="com.aska.app_updater",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        )
        self.connect("startup", self.on_startup)
        self.connect("command-line", self.on_command_line)
        self.is_background = False
        
        # Add command line options
        self.add_main_option(
            "background",
            ord('b'),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Run application in the background",
            None
        )
        self.add_main_option(
            "refresh",
            ord('r'),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Trigger update check",
            None
        )
        self.add_main_option(
            "quit",
            ord('q'),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Quit the application",
            None
        )


    def on_startup(self, app: Adw.Application) -> None:
        # App-wide quit action (Ctrl+Q)
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda a, p: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

        # Show window action (triggered by clicking notification or tray)
        show_action = Gio.SimpleAction.new("show-window", None)
        show_action.connect("activate", self.on_show_window)
        self.add_action(show_action)

        # Refresh action (triggered by tray menu)
        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", self.on_app_refresh)
        self.add_action(refresh_action)
        
        # Setup desktop integration (.desktop files and autostart entry)
        self.setup_desktop_integration()

    def on_show_window(self, action: Gio.SimpleAction, param: GLib.Variant | None) -> None:
        windows = self.get_windows()
        if windows:
            win = windows[0]
            win.set_visible(True)
            win.present()

    def on_app_refresh(self, action: Gio.SimpleAction, param: GLib.Variant | None) -> None:
        windows = self.get_windows()
        if windows:
            win = windows[0]
            win.check_for_updates()

    def setup_desktop_integration(self) -> None:
        """Creates .desktop application launcher and autostart entry for background execution."""
        try:
            home = os.path.expanduser("~")
            apps_dir = os.path.join(home, ".local", "share", "applications")
            autostart_dir = os.path.join(home, ".config", "autostart")
            
            os.makedirs(apps_dir, exist_ok=True)
            os.makedirs(autostart_dir, exist_ok=True)
            
            current_dir = os.path.dirname(os.path.abspath(__file__))
            main_script = os.path.join(current_dir, "main.py")
            interpreter = sys.executable
            
            desktop_content = f"""[Desktop Entry]
Name=App Updater
Comment=Update system packages, Flatpaks, Snaps, and AppImages
Exec="{interpreter}" "{main_script}"
Icon=system-software-update
Terminal=false
Type=Application
Categories=System;Settings;
StartupNotify=true
X-GNOME-Autostart-enabled=true
"""
            
            # Write to ~/.local/share/applications/com.aska.app_updater.desktop
            desktop_path = os.path.join(apps_dir, "com.aska.app_updater.desktop")
            if not os.path.exists(desktop_path):
                with open(desktop_path, "w") as f:
                    f.write(desktop_content)
                    
            # Write autostart entry to ~/.config/autostart/com.aska.app_updater.desktop
            # Note: Autostart version runs with --background flag
            autostart_content = f"""[Desktop Entry]
Name=App Updater Daemon
Comment=Start App Updater tray icon in background
Exec="{interpreter}" "{main_script}" --background
Icon=system-software-update
Terminal=false
Type=Application
X-GNOME-Autostart-enabled=true
"""
            autostart_path = os.path.join(autostart_dir, "com.aska.app_updater.desktop")
            if not os.path.exists(autostart_path):
                with open(autostart_path, "w") as f:
                    f.write(autostart_content)
                    
        except Exception as e:
            print(f"Failed to setup desktop integration: {e}")

    def on_command_line(self, app: Adw.Application, command_line: Gio.ApplicationCommandLine) -> int:
        options = command_line.get_options_dict()
        self.is_background = options.contains("background")
        is_refresh = options.contains("refresh")
        is_quit = options.contains("quit")
        
        if is_quit:
            self.quit()
            return 0
            
        windows = self.get_windows()
        if not windows:
            self.win = AppUpdaterWindow(application=self)
        else:
            self.win = windows[0]
            
        if is_refresh:
            self.win.check_for_updates()
            
        if not self.is_background:
            self.win.set_visible(True)
            self.win.present()
        else:
            self.win.set_visible(False)
            
        return 0
