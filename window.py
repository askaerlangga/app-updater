import os
import threading
import shutil
import subprocess
from collections import defaultdict
from typing import Dict, Any, List
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, GLib, Adw, Gio

import updater_backend
from settings import SettingsManager

class AppUpdaterWindow(Adw.ApplicationWindow):
    """Main window UI for the App Updater application."""
    
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_title("App Updater")
        self.set_default_size(680, 520)
        
        # Load settings
        self.settings_manager = SettingsManager()
        
        # Load CSS Styles
        self.setup_styles()
        
        # Main layout structure
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(self.main_box)
        
        # Header Bar
        self.header_bar = Adw.HeaderBar()
        self.main_box.append(self.header_bar)
        
        # Header Bar Buttons
        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        self.refresh_btn.set_action_name("win.refresh")
        self.refresh_btn.set_tooltip_text("Check for Updates (Ctrl+R)")
        self.header_bar.pack_start(self.refresh_btn)
        
        # Main Menu Button
        self.menu_button = Gtk.MenuButton()
        self.menu_button.set_icon_name("open-menu-symbolic")
        self.menu_button.set_tooltip_text("Menu")
        self.header_bar.pack_end(self.menu_button)

        menu_model = Gio.Menu.new()
        menu_model.append("Preferences", "win.preferences")
        menu_model.append("Keyboard Shortcuts", "win.shortcuts")
        menu_model.append("About App Updater", "win.about")
        self.menu_button.set_menu_model(menu_model)

        # Overlay to allow the terminal log to overlay the entire view container in full window mode
        self.overlay = Gtk.Overlay()
        self.overlay.set_vexpand(True)
        self.overlay.set_hexpand(True)
        self.main_box.append(self.overlay)
        
        # View Container
        self.view_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.view_container.set_vexpand(True)
        self.view_container.set_hexpand(True)
        self.overlay.set_child(self.view_container)
        
        # Preferences Page (main layout of cards)
        self.pref_page = Adw.PreferencesPage()
        self.view_container.append(self.pref_page)
        
        # Create main updates group
        self.updates_group = Adw.PreferencesGroup(title="Available Updates")
        
        # Status Page (when up to date or checking)
        self.status_page = Adw.StatusPage()
        self.status_page.set_title("Loading...")
        self.status_page.set_description("Checking for available updates...")
        self.status_page.set_icon_name("system-software-update-symbolic")
        self.status_page.set_vexpand(True)
        self.status_page.set_hexpand(True)
        self.view_container.append(self.status_page)
        
        # Status Box to hold spinner and cancel button
        self.status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.status_box.set_halign(Gtk.Align.CENTER)
        self.status_box.set_valign(Gtk.Align.CENTER)
        self.status_page.set_child(self.status_box)
        
        # Loading Spinner Overlay
        self.spinner = Adw.Spinner()
        self.spinner.set_halign(Gtk.Align.CENTER)
        self.spinner.set_valign(Gtk.Align.CENTER)
        self.status_box.append(self.spinner)
        
        # Cancel Button (will be appended to status_box)
        self.cancel_btn = Gtk.Button(label="Cancel Updates")
        self.cancel_btn.add_css_class("destructive-action")
        self.cancel_btn.add_css_class("pill")
        self.cancel_btn.set_halign(Gtk.Align.CENTER)
        self.cancel_btn.set_visible(False)
        self.cancel_btn.connect("clicked", self.on_cancel_clicked)
        self.status_box.append(self.cancel_btn)
        
        # Bottom container for log expander (placed at the bottom-left of the window as an overlay)
        self.bottom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.bottom_box.set_halign(Gtk.Align.START)
        self.bottom_box.set_valign(Gtk.Align.END)
        self.bottom_box.set_margin_start(16)
        self.bottom_box.set_margin_bottom(16)
        self.bottom_box.set_visible(False)
        self.overlay.add_overlay(self.bottom_box)
        
        # Setup Log Expander
        self.setup_log_expander()
        
        # Create a group for the update all button
        self.button_group = Adw.PreferencesGroup()
        
        # Button Container for "Update All"
        self.button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.button_box.set_halign(Gtk.Align.CENTER)
        self.button_box.set_margin_bottom(16)
        self.button_box.set_margin_top(8)
        
        self.update_all_btn = Gtk.Button(label="Update All")
        self.update_all_btn.set_action_name("win.update-all")
        self.update_all_btn.add_css_class("suggested-action")
        self.update_all_btn.add_css_class("pill")
        self.update_all_btn.set_sensitive(False)
        self.button_box.append(self.update_all_btn)
        self.button_group.add(self.button_box)
        
        # Data states
        self.updates_data: Dict[str, List[Dict[str, Any]]] = {
            'APT': [],
            'Flatpak': [],
            'Snap': [],
            'AppImage': []
        }
        self.added_groups = set()
        
        # Setup Window Actions (GActions)
        self.setup_actions()
        
        # Periodic update check every 4 hours
        GLib.timeout_add_seconds(4 * 3600, self.periodic_check_updates)
        
        # Start initial check
        self.check_for_updates()

    def setup_styles(self) -> None:
        """Injects custom CSS styling for the terminal log console."""
        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
            .terminal {
                font-family: monospace;
                background-color: #1e1e2e;
                color: #a6e3a1;
                font-size: 10.5pt;
            }
            .terminal-container {
                border: 1px solid @borders;
                border-radius: 8px;
                background-color: #1e1e2e;
            }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def setup_log_expander(self) -> None:
        """Creates the console log area inside an expander (dropdown) on the status page."""
        self.log_expander = Gtk.Expander(label="Show Details")
        self.log_expander.set_margin_top(8)
        self.log_expander.set_margin_bottom(8)
        self.log_expander.set_visible(False)
        self.bottom_box.append(self.log_expander)
        
        # Connect to expander signal to toggle full window mode
        self.log_expander.connect("notify::expanded", self.on_log_expander_expanded)
        
        # Scrolled Text View for Terminal output
        self.log_scrolled = Gtk.ScrolledWindow()
        self.log_scrolled.set_min_content_width(540)
        self.log_scrolled.set_min_content_height(200)
        self.log_scrolled.set_max_content_height(300)
        self.log_scrolled.add_css_class("terminal-container")
        self.log_expander.set_child(self.log_scrolled)
        
        self.log_text_view = Gtk.TextView()
        self.log_text_view.set_editable(False)
        self.log_text_view.set_cursor_visible(False)
        self.log_text_view.set_monospace(True)
        self.log_text_view.add_css_class("terminal")
        self.log_text_view.set_left_margin(10)
        self.log_text_view.set_right_margin(10)
        self.log_text_view.set_top_margin(10)
        self.log_text_view.set_bottom_margin(10)
        self.log_scrolled.set_child(self.log_text_view)
        
        self.log_buffer = self.log_text_view.get_buffer()
        self.log_scroll_mark = self.log_buffer.create_mark("scroll-mark", self.log_buffer.get_end_iter(), False)

    def on_log_expander_expanded(self, expander: Gtk.Expander, pspec: Any) -> None:
        """Toggles full window expansion mode for the terminal console."""
        if expander.get_expanded():
            self.bottom_box.set_halign(Gtk.Align.FILL)
            self.bottom_box.set_valign(Gtk.Align.FILL)
            self.bottom_box.set_margin_start(0)
            self.bottom_box.set_margin_bottom(0)
            self.bottom_box.set_margin_top(0)
            self.bottom_box.set_margin_end(0)
            
            self.log_scrolled.set_min_content_width(-1)
            self.log_scrolled.set_min_content_height(-1)
            self.log_scrolled.set_max_content_height(-1)
            self.log_scrolled.set_vexpand(True)
            self.log_scrolled.set_hexpand(True)
            self.log_text_view.set_vexpand(True)
            self.log_text_view.set_hexpand(True)
        else:
            self.bottom_box.set_halign(Gtk.Align.START)
            self.bottom_box.set_valign(Gtk.Align.END)
            self.bottom_box.set_margin_start(16)
            self.bottom_box.set_margin_bottom(16)
            self.bottom_box.set_margin_top(0)
            self.bottom_box.set_margin_end(0)
            
            self.log_scrolled.set_min_content_width(540)
            self.log_scrolled.set_min_content_height(200)
            self.log_scrolled.set_max_content_height(300)
            self.log_scrolled.set_vexpand(False)
            self.log_scrolled.set_hexpand(False)
            self.log_text_view.set_vexpand(False)
            self.log_text_view.set_hexpand(False)

    def append_log_line(self, line: str) -> None:
        """Safely appends a line to the text console from a worker thread."""
        GLib.idle_add(self._append_log_line_ui, line)

    def _append_log_line_ui(self, line: str) -> None:
        end_iter = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end_iter, line)
        self.log_buffer.move_mark(self.log_scroll_mark, self.log_buffer.get_end_iter())
        self.log_text_view.scroll_to_mark(self.log_scroll_mark, 0.0, True, 0.0, 1.0)

    def set_loading(self, loading: bool, title: str = "Loading...", desc: str = "Checking for updates...", allow_cancel: bool = False, is_updating: bool = False) -> None:
        """Toggles loading state UI."""
        if hasattr(self, "refresh_action"):
            self.refresh_action.set_enabled(not loading)
        if hasattr(self, "update_all_action"):
            self.update_all_action.set_enabled(False)
            
        self.refresh_btn.set_sensitive(not loading)
        self.update_all_btn.set_sensitive(False)
        
        if loading:
            self.spinner.set_visible(True)
            self.status_page.set_title(title)
            self.status_page.set_description(desc)
            self.status_page.set_visible(True)
            self.pref_page.set_visible(False)
            
            self.log_expander.set_visible(is_updating)
            if is_updating:
                self.log_expander.set_expanded(False)
                
            self.cancel_btn.set_visible(allow_cancel)
            self.cancel_btn.set_sensitive(True)
            
            self.bottom_box.set_visible(is_updating)
        else:
            self.spinner.set_visible(False)
            self.cancel_btn.set_visible(False)
            self.log_expander.set_visible(False)
            self.bottom_box.set_visible(False)

    def on_cancel_clicked(self, btn: Gtk.Button) -> None:
        btn.set_sensitive(False)
        self.status_page.set_description("Canceling updates, please wait...")
        updater_backend.cancel_updates()

    def check_for_updates(self) -> None:
        """Spawns background threads to check for updates."""
        self.set_loading(True)
        
        # Remove existing preferences groups from page
        for group in list(self.added_groups):
            try:
                self.pref_page.remove(group)
            except Exception:
                pass
        self.added_groups.clear()
                
        def thread_func():
            # Run checks based on enabled settings
            apt_list = updater_backend.check_apt_updates() if self.settings_manager.get("apt_enabled", True) else []
            flatpak_list = updater_backend.check_flatpak_updates() if self.settings_manager.get("flatpak_enabled", True) else []
            snap_list = updater_backend.check_snap_updates() if self.settings_manager.get("snap_enabled", True) else []
            appimage_list = updater_backend.check_appimage_updates() if self.settings_manager.get("appimage_enabled", True) else []
            
            data = {
                'APT': apt_list,
                'Flatpak': flatpak_list,
                'Snap': snap_list,
                'AppImage': appimage_list
            }
            GLib.idle_add(self.on_checks_completed, data)
            
        threading.Thread(target=thread_func, daemon=True).start()

    def on_checks_completed(self, data: Dict[str, List[Dict[str, Any]]]) -> None:
        self.updates_data = data
        self.set_loading(False)
        
        total_updates = 0
        
        # Remove existing preferences groups from page to clear them
        for group in list(self.added_groups):
            try:
                self.pref_page.remove(group)
            except Exception:
                pass
        self.added_groups.clear()
                
        # Recreate updates group
        self.updates_group = Adw.PreferencesGroup(title="Available Updates")
        has_group_content = False
                
        # Populate APT Group
        if data['APT']:
            self.apt_expander = Adw.ExpanderRow(
                title="System Updates (APT)",
                subtitle=f"{len(data['APT'])} packages can be updated"
            )
            update_btn = Gtk.Button(icon_name="software-update-available-symbolic")
            update_btn.set_has_frame(False)
            update_btn.set_tooltip_text("Update APT packages only")
            update_btn.connect("clicked", lambda b: self.on_update_single_clicked("APT"))
            self.apt_expander.add_suffix(update_btn)
            
            self.updates_group.add(self.apt_expander)
            has_group_content = True
            total_updates += len(data['APT'])
            grouped_apt = defaultdict(list)
            for pkg in data['APT']:
                s_name = pkg.get('source_name') or pkg['name']
                grouped_apt[s_name].append(pkg)
                
            for s_name in sorted(grouped_apt.keys()):
                packages = grouped_apt[s_name]
                if len(packages) > 1:
                    sub_expander = Adw.ExpanderRow(
                        title=s_name,
                        subtitle=f"{len(packages)} packages ({', '.join(p['name'] for p in packages[:2])}...)"
                    )
                    icon_candidates = self.get_apt_icon_candidates(s_name)
                    icon_image = self.get_app_icon(icon_candidates, fallback="package-x-generic-symbolic")
                    sub_expander.add_prefix(icon_image)
                    
                    for pkg in packages:
                        row = Adw.ActionRow(
                            title=pkg['name'],
                            subtitle=f"Installed: {pkg['current_version']} → Candidate: {pkg['new_version']} ({pkg['size']})"
                        )
                        sub_expander.add_row(row)
                        
                    self.apt_expander.add_row(sub_expander)
                else:
                    pkg = packages[0]
                    row = Adw.ActionRow(
                        title=pkg['name'],
                        subtitle=f"Installed: {pkg['current_version']} → Candidate: {pkg['new_version']} ({pkg['size']})"
                    )
                    icon_candidates = self.get_apt_icon_candidates(pkg['name'])
                    icon_image = self.get_app_icon(icon_candidates, fallback="package-x-generic-symbolic")
                    row.add_prefix(icon_image)
                    self.apt_expander.add_row(row)
                
        # Populate Flatpak Group
        if data['Flatpak']:
            self.flatpak_expander = Adw.ExpanderRow(
                title="Flatpak Applications",
                subtitle=f"{len(data['Flatpak'])} applications can be updated"
            )
            update_btn = Gtk.Button(icon_name="software-update-available-symbolic")
            update_btn.set_has_frame(False)
            update_btn.set_tooltip_text("Update Flatpak applications only")
            update_btn.connect("clicked", lambda b: self.on_update_single_clicked("Flatpak"))
            self.flatpak_expander.add_suffix(update_btn)
            
            self.updates_group.add(self.flatpak_expander)
            has_group_content = True
            total_updates += len(data['Flatpak'])
            for app in data['Flatpak']:
                row = Adw.ActionRow(
                    title=app['name'],
                    subtitle=f"ID: {app['id']} | New version: {app['new_version']} ({app['size']})"
                )
                icon_candidates = self.get_flatpak_icon_candidates(app['id'])
                icon_image = self.get_app_icon(icon_candidates)
                row.add_prefix(icon_image)
                self.flatpak_expander.add_row(row)
                
        # Populate Snap Group
        if data['Snap']:
            self.snap_expander = Adw.ExpanderRow(
                title="Snap Applications",
                subtitle=f"{len(data['Snap'])} applications can be updated"
            )
            update_btn = Gtk.Button(icon_name="software-update-available-symbolic")
            update_btn.set_has_frame(False)
            update_btn.set_tooltip_text("Update Snap applications only")
            update_btn.connect("clicked", lambda b: self.on_update_single_clicked("Snap"))
            self.snap_expander.add_suffix(update_btn)
            
            self.updates_group.add(self.snap_expander)
            has_group_content = True
            total_updates += len(data['Snap'])
            for snap in data['Snap']:
                row = Adw.ActionRow(
                    title=snap['name'],
                    subtitle=f"New version: {snap['new_version']}"
                )
                icon_image = self.get_app_icon(snap['name'])
                row.add_prefix(icon_image)
                self.snap_expander.add_row(row)
                
        # Populate AppImage Group
        appimages = data['AppImage']
        has_appimages = len(appimages) > 0
        
        if has_appimages:
            tool_missing = any(ai.get('tool_missing') for ai in appimages)
            if not tool_missing:
                upgradable_count = sum(1 for ai in appimages if ai.get('upgradable'))
                
                if upgradable_count > 0:
                    total_updates += upgradable_count
                    self.appimage_expander = Adw.ExpanderRow(
                        title="AppImage Applications",
                        subtitle=f"{upgradable_count} applications can be updated"
                    )
                    update_btn = Gtk.Button(icon_name="software-update-available-symbolic")
                    update_btn.set_has_frame(False)
                    update_btn.set_tooltip_text("Update AppImage applications only")
                    update_btn.connect("clicked", lambda b: self.on_update_single_clicked("AppImage"))
                    self.appimage_expander.add_suffix(update_btn)
                    
                    self.updates_group.add(self.appimage_expander)
                    has_group_content = True
                    
                    for ai in appimages:
                        row = Adw.ActionRow(
                            title=ai['name'],
                            subtitle=f"Status: {ai['new_version']}"
                        )
                        clean_name = ai['name'].lower().replace(" ", "").replace("-", "").replace("_", "")
                        icon_image = self.get_app_icon(clean_name)
                        row.add_prefix(icon_image)
                        self.appimage_expander.add_row(row)

        if has_group_content:
            self.pref_page.add(self.updates_group)
            self.added_groups.add(self.updates_group)
            
            self.pref_page.add(self.button_group)
            self.added_groups.add(self.button_group)

        # Toggle UI views based on updates found
        self.settings_manager.save_state(total_updates, updating=False)
        if total_updates > 0:
            self.status_page.set_visible(False)
            self.pref_page.set_visible(True)
            self.update_all_btn.set_sensitive(True)
            if hasattr(self, "update_all_action"):
                self.update_all_action.set_enabled(True)
            
            # Send notification if the window is hidden (in background mode)
            if not self.get_visible():
                self.send_update_notification(total_updates)
        else:
            # If running in background mode and no updates found, exit to save resources
            if not self.get_visible():
                self.get_application().quit()
                return

            self.status_page.set_visible(True)
            self.pref_page.set_visible(False)
            self.status_page.set_title("System Up to Date")
            self.status_page.set_description("All applications and system packages are up to date.")
            self.update_all_btn.set_sensitive(False)
            if hasattr(self, "update_all_action"):
                self.update_all_action.set_enabled(False)

    def on_refresh_clicked(self, btn: Gtk.Button) -> None:
        self.check_for_updates()

    def on_download_tool_clicked(self, btn: Gtk.Button) -> None:
        if btn is not None:
            btn.set_sensitive(False)
        self.set_loading(True, title="Downloading Tool...", desc="Downloading appimageupdatetool from GitHub...")
        
        def done_callback(success: bool):
            GLib.idle_add(self._on_download_completed, success)
            
        def thread_func():
            success = updater_backend.download_appimage_tool()
            done_callback(success)
            
        threading.Thread(target=thread_func, daemon=True).start()

    def _on_download_completed(self, success: bool) -> None:
        self.set_loading(False)
        if success:
            self.check_for_updates()
        else:
            dialog = Adw.AlertDialog(
                heading="Download Failed",
                body="Unable to download appimageupdatetool. Please check your internet connection."
            )
            dialog.add_response("ok", "OK")
            dialog.present(self)

    def on_update_single_clicked(self, source_name: str) -> None:
        self.start_updates([source_name])

    def check_battery_status(self) -> tuple[bool, float]:
        """Returns (on_battery, percentage) using UPower over D-Bus."""
        try:
            dbus_conn = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            
            # Check if OnBattery
            res_on_battery = dbus_conn.call_sync(
                "org.freedesktop.UPower",
                "/org/freedesktop/UPower",
                "org.freedesktop.DBus.Properties",
                "Get",
                GLib.Variant("(ss)", ("org.freedesktop.UPower", "OnBattery")),
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None
            )
            on_battery = res_on_battery.unpack()[0]
            
            # Get display device percentage
            res_percentage = dbus_conn.call_sync(
                "org.freedesktop.UPower",
                "/org/freedesktop/UPower/devices/DisplayDevice",
                "org.freedesktop.DBus.Properties",
                "Get",
                GLib.Variant("(ss)", ("org.freedesktop.UPower.Device", "Percentage")),
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None
            )
            percentage = res_percentage.unpack()[0]
            return on_battery, percentage
        except Exception:
            return False, 100.0

    def start_updates(self, sources_to_update: List[str]) -> None:
        if not sources_to_update:
            return
            
        on_battery, percentage = self.check_battery_status()
        
        heading = "Start System Updates?"
        body = "Applying updates can take several minutes. Please make sure your device is connected to a power source or has sufficient battery before starting."
        appearance = Adw.ResponseAppearance.SUGGESTED
        
        # If running on low battery, warn the user and change to destructive appearance
        if on_battery and percentage < 25.0:
            heading = "Warning: Low Battery"
            body = f"Your device is running on battery power ({percentage:.0f}%) and is not connected to a charger. Running system updates on a low battery is risky and can cause system corruption if the device powers off midway. We strongly recommend plugging in your charger."
            appearance = Adw.ResponseAppearance.DESTRUCTIVE
            
        dialog = Adw.AlertDialog(
            heading=heading,
            body=body
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("update", "Update")
        dialog.set_default_response("update")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("update", appearance)
        
        def on_response(d, response_id):
            if response_id == "update":
                self._execute_start_updates(sources_to_update)
                
        dialog.connect("response", on_response)
        dialog.present(self)

    def _execute_start_updates(self, sources_to_update: List[str]) -> None:
        self.settings_manager.save_state(0, updating=True)
            
        self.set_loading(True, title="Installing Updates...", desc="Applying system and application updates, please wait...", allow_cancel=True, is_updating=True)
        self.log_buffer.set_text("")
        
        self.refresh_btn.set_sensitive(False)
        self.update_all_btn.set_sensitive(False)
        self.pref_page.set_sensitive(False)
        
        self.refresh_action.set_enabled(False)
        self.update_all_action.set_enabled(False)
        self.pref_action.set_enabled(False)
        
        def done_callback(success: bool, message: str):
            GLib.idle_add(self.on_updates_finished, success, message)
            
        updater_backend.execute_updates(
            sources_to_update,
            self.append_log_line,
            done_callback
        )

    def on_update_all_clicked(self, btn: Gtk.Button) -> None:
        sources_to_update = []
        if self.updates_data['APT']:
            sources_to_update.append('APT')
        if self.updates_data['Flatpak']:
            sources_to_update.append('Flatpak')
        if self.updates_data['Snap']:
            sources_to_update.append('Snap')
        if self.updates_data['AppImage']:
            if any(ai.get('upgradable') for ai in self.updates_data['AppImage']):
                sources_to_update.append('AppImage')
                
        self.start_updates(sources_to_update)

    def on_updates_finished(self, success: bool, message: str) -> None:
        self.refresh_btn.set_sensitive(True)
        self.pref_page.set_sensitive(True)
        self.refresh_action.set_enabled(True)
        self.pref_action.set_enabled(True)
        self.check_for_updates()
        
        title = "Update Successful" if success else "Update Completed with Warnings"
        body = "All updates have been successfully applied." if success else f"An error occurred: {message}"
        
        dialog = Adw.AlertDialog(
            heading=title,
            body=body
        )
        dialog.add_response("ok", "OK")
        dialog.present(self)

    def setup_actions(self) -> None:
        """Initializes simple actions mapping buttons and keyboard shortcuts."""
        self.refresh_action = Gio.SimpleAction.new("refresh", None)
        self.refresh_action.connect("activate", lambda a, p: self.check_for_updates())
        self.add_action(self.refresh_action)
        self.get_application().set_accels_for_action("win.refresh", ["<Control>r"])

        self.pref_action = Gio.SimpleAction.new("preferences", None)
        self.pref_action.connect("activate", lambda a, p: self.on_preferences_clicked(None))
        self.add_action(self.pref_action)
        self.get_application().set_accels_for_action("win.preferences", ["<Control>comma"])

        # About Action
        self.about_action = Gio.SimpleAction.new("about", None)
        self.about_action.connect("activate", self.on_about_clicked)
        self.add_action(self.about_action)

        # Shortcuts Action
        self.shortcuts_action = Gio.SimpleAction.new("shortcuts", None)
        self.shortcuts_action.connect("activate", self.on_shortcuts_clicked)
        self.add_action(self.shortcuts_action)
        self.get_application().set_accels_for_action("win.shortcuts", ["<Control>question"])

        self.update_all_action = Gio.SimpleAction.new("update-all", None)
        self.update_all_action.connect("activate", lambda a, p: self.on_update_all_clicked(None))
        self.add_action(self.update_all_action)
        self.get_application().set_accels_for_action("win.update-all", ["<Control>u"])

    def get_app_icon(self, icon_names: List[str] | str, fallback: str = "application-x-executable-symbolic") -> Gtk.Image:
        if isinstance(icon_names, str):
            icon_names = [icon_names]
            
        display = Gdk.Display.get_default()
        if display:
            icon_theme = Gtk.IconTheme.get_for_display(display)
            for name in icon_names:
                if name and icon_theme.has_icon(name):
                    img = Gtk.Image.new_from_icon_name(name)
                    img.set_pixel_size(24)
                    return img
        img = Gtk.Image.new_from_icon_name(fallback)
        img.set_pixel_size(24)
        return img

    def get_apt_icon_candidates(self, pkg_name: str) -> List[str]:
        candidates = [pkg_name]
        suffixes = [
            "-common", "-data", "-bin", "-desktop", "-gtk", "-qt", "-core", 
            "-client", "-server", "-lib", "-dev", "-utils", "-tools", "-plugin", 
            "-plugins", "-l10n", "-help", "-extension", "-extensions"
        ]
        
        clean = pkg_name
        for suffix in suffixes:
            if clean.endswith(suffix):
                clean = clean[:-len(suffix)]
                candidates.append(clean)
                
        if pkg_name.startswith("python3-"):
            pure = pkg_name[8:]
            candidates.append(pure)
            candidates.append("python3")
            candidates.append("python")
        elif pkg_name.startswith("python-"):
            pure = pkg_name[7:]
            candidates.append(pure)
            candidates.append("python")
        elif pkg_name.startswith("lib"):
            pure = pkg_name[3:]
            candidates.append(pure)
            parts = pure.split("-")
            if len(parts) > 1:
                candidates.append(parts[0])
                
        if "-" in clean:
            parts = clean.split("-")
            for i in range(len(parts) - 1, 0, -1):
                candidates.append("-".join(parts[:i]))
                
        expanded_candidates = []
        for c in candidates:
            expanded_candidates.append(c)
            if not c.endswith("-startcenter"):
                expanded_candidates.append(c + "-startcenter")
            if not c.endswith("-main"):
                expanded_candidates.append(c + "-main")

        seen = set()
        unique_candidates = []
        for c in expanded_candidates:
            if c not in seen:
                seen.add(c)
                unique_candidates.append(c)
        return unique_candidates

    def get_flatpak_icon_candidates(self, app_id: str) -> List[str]:
        candidates = [app_id]
        parts = app_id.split('.')
        if len(parts) > 1:
            last = parts[-1]
            candidates.append(last)
            candidates.append(last.lower())
            
            if last.lower() in ['client', 'app', 'desktop', 'bin', 'common'] and len(parts) > 2:
                prev = parts[-2]
                candidates.append(prev)
                candidates.append(prev.lower())
                
        seen = set()
        unique = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique

    def on_setting_changed(self, key: str, value: Any) -> None:
        self.settings_manager.set(key, value)
        self.check_for_updates()

    def on_appimage_toggle_changed(self, row: Adw.SwitchRow, pref_dialog: Adw.PreferencesDialog) -> None:
        active = row.get_active()
        tool_installed = bool(updater_backend.get_appimage_tool())
        
        if active and not tool_installed:
            dialog = Adw.AlertDialog(
                heading="Install appimageupdatetool?",
                body="The appimageupdatetool is required to automatically check and apply updates for AppImages. Would you like to download it now?"
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("install", "Install")
            dialog.set_default_response("install")
            
            def on_response(d, response_id):
                if response_id == "install":
                    pref_dialog.close()
                    self.settings_manager.set("appimage_enabled", True)
                    self.on_download_tool_clicked(None)
                else:
                    row.handler_block(self.appimage_handler_id)
                    row.set_active(False)
                    row.handler_unblock(self.appimage_handler_id)
                    
            dialog.connect("response", on_response)
            dialog.present(self)
        else:
            self.on_setting_changed("appimage_enabled", active)
  
    def on_preferences_clicked(self, btn: Gtk.Button | None) -> None:
        pref_win = Adw.PreferencesDialog(title="Preferences")
        
        page = Adw.PreferencesPage(title="General Settings")
        pref_win.add(page)
        
        group = Adw.PreferencesGroup(title="Optional Package Sources")
        page.add(group)
        
        # Check system support dynamically
        has_apt = bool(shutil.which("apt-get") or shutil.which("dpkg"))
        has_flatpak = bool(shutil.which("flatpak"))
        has_snap = bool(shutil.which("snap"))
        
        # AppImage check
        appimage_dir = os.path.expanduser("~/Applications")
        has_appimages = False
        if os.path.exists(appimage_dir):
            try:
                has_appimages = any(f.lower().endswith('.appimage') for f in os.listdir(appimage_dir))
            except Exception:
                pass
        tool_installed = bool(updater_backend.get_appimage_tool())
        has_appimage = has_appimages or tool_installed

        apt_row = None
        if has_apt:
            apt_row = Adw.SwitchRow(title="APT")
            apt_row.set_active(self.settings_manager.get("apt_enabled", True))
            apt_row.connect("notify::active", lambda row, pspec: self.on_setting_changed("apt_enabled", row.get_active()))
            group.add(apt_row)
        else:
            self.settings_manager.set("apt_enabled", False)
            
        flatpak_row = None
        if has_flatpak:
            flatpak_row = Adw.SwitchRow(title="Flatpak")
            flatpak_row.set_active(self.settings_manager.get("flatpak_enabled", True))
            flatpak_row.connect("notify::active", lambda row, pspec: self.on_setting_changed("flatpak_enabled", row.get_active()))
            group.add(flatpak_row)
        else:
            self.settings_manager.set("flatpak_enabled", False)
            
        snap_row = None
        if has_snap:
            snap_row = Adw.SwitchRow(title="Snap")
            snap_row.set_active(self.settings_manager.get("snap_enabled", True))
            snap_row.connect("notify::active", lambda row, pspec: self.on_setting_changed("snap_enabled", row.get_active()))
            group.add(snap_row)
        else:
            self.settings_manager.set("snap_enabled", False)
            
        appimage_row = None
        if has_appimage:
            appimage_row = Adw.SwitchRow(title="AppImage")
            appimage_row.set_active(self.settings_manager.get("appimage_enabled", True) and tool_installed)
            
            self.appimage_handler_id = appimage_row.connect(
                "notify::active", 
                lambda row, pspec: self.on_appimage_toggle_changed(row, pref_win)
            )
            group.add(appimage_row)
        else:
            self.settings_manager.set("appimage_enabled", False)
            
        self.update_preferences_subtitles(apt_row, flatpak_row, snap_row, appimage_row)
            
        pref_win.present(self)

    def on_shortcuts_clicked(self, action: Gio.SimpleAction, param: GLib.Variant | None) -> None:
        dialog = Adw.ShortcutsDialog()
        
        # General Section
        section_general = Adw.ShortcutsSection(title="General")
        
        section_general.add(Adw.ShortcutsItem(
            title="Scan for Updates",
            accelerator="<Control>r"
        ))
        section_general.add(Adw.ShortcutsItem(
            title="Open Preferences",
            accelerator="<Control>comma"
        ))
        section_general.add(Adw.ShortcutsItem(
            title="Keyboard Shortcuts",
            accelerator="<Control>question"
        ))
        section_general.add(Adw.ShortcutsItem(
            title="Quit Application",
            accelerator="<Control>q"
        ))
        
        dialog.add(section_general)
        
        # System Updates Section
        section_updates = Adw.ShortcutsSection(title="System Updates")
        section_updates.add(Adw.ShortcutsItem(
            title="Update All Packages",
            accelerator="<Control>u"
        ))
        
        dialog.add(section_updates)
        dialog.present(self)

    def on_about_clicked(self, action: Gio.SimpleAction, param: GLib.Variant | None) -> None:
        about = Adw.AboutDialog(
            application_name="App Updater",
            application_icon="system-software-update",
            version="1.1.0",
            developer_name="Aska Erlangga",
            developers=["Aska Erlangga"],
            copyright="© 2026 Aska Erlangga",
            license_type=Gtk.License.GPL_3_0,
            comments="A unified graphical package updater for Linux (APT, Flatpak, Snap, AppImage)."
        )
        about.present(self)

    def update_preferences_subtitles(self, apt_row: Adw.SwitchRow | None, flatpak_row: Adw.SwitchRow | None, snap_row: Adw.SwitchRow | None, appimage_row: Adw.SwitchRow | None) -> None:
        if apt_row:
            apt_row.set_subtitle("Checking installed packages...")
        if flatpak_row:
            flatpak_row.set_subtitle("Checking installed applications...")
        if snap_row:
            snap_row.set_subtitle("Checking installed applications...")
        
        tool_installed = bool(updater_backend.get_appimage_tool())
        if appimage_row:
            if tool_installed:
                appimage_row.set_subtitle("Checking AppImage files...")
            else:
                appimage_row.set_subtitle("Checking AppImage files... (requires appimageupdatetool)")
            
        def worker():
            # 1. APT Count
            apt_sub = ""
            if apt_row:
                try:
                    if shutil.which("dpkg-query"):
                        res = subprocess.run(["dpkg-query", "-W", "-f", "${Package}\n"], capture_output=True, text=True)
                        apt_count = res.stdout.count('\n')
                    else:
                        import apt
                        cache = apt.Cache()
                        apt_count = sum(1 for pkg in cache if pkg.is_installed)
                    apt_sub = f"{apt_count:,} system packages installed"
                except Exception:
                    apt_sub = "APT package status unavailable"
                
            # 2. Flatpak Count
            flatpak_sub = ""
            if flatpak_row:
                if shutil.which("flatpak"):
                    try:
                        res = subprocess.run(["flatpak", "list", "--app"], capture_output=True, text=True)
                        flatpak_count = res.stdout.count('\n')
                        flatpak_sub = f"{flatpak_count} Flatpak applications installed"
                    except Exception:
                        flatpak_sub = "Flatpak applications status unavailable"
                else:
                    flatpak_sub = "Flatpak is not installed"
                
            # 3. Snap Count
            snap_sub = ""
            if snap_row:
                if shutil.which("snap"):
                    try:
                        res = subprocess.run(["snap", "list"], capture_output=True, text=True)
                        lines = res.stdout.count('\n')
                        snap_count = lines - 1 if lines > 1 else 0
                        snap_sub = f"{snap_count} Snap applications installed"
                    except Exception:
                        snap_sub = "Snap applications status unavailable"
                else:
                    snap_sub = "Snap is not installed"
                
            # 4. AppImage Count
            appimage_sub = ""
            if appimage_row:
                appimage_count = 0
                appimage_dir = os.path.expanduser("~/Applications")
                if os.path.exists(appimage_dir):
                    try:
                        appimage_count = len([f for f in os.listdir(appimage_dir) if f.lower().endswith('.appimage')])
                    except Exception:
                        pass
                
                if tool_installed:
                    appimage_sub = f"{appimage_count} AppImage files found in ~/Applications"
                else:
                    appimage_sub = f"{appimage_count} AppImage files found (requires appimageupdatetool, toggle to install)"
                
            def apply_ui_updates():
                if apt_row:
                    try:
                        apt_row.set_subtitle(apt_sub)
                    except Exception:
                        pass
                if flatpak_row:
                    try:
                        flatpak_row.set_subtitle(flatpak_sub)
                    except Exception:
                        pass
                if snap_row:
                    try:
                        snap_row.set_subtitle(snap_sub)
                    except Exception:
                        pass
                if appimage_row:
                    try:
                        appimage_row.set_subtitle(appimage_sub)
                    except Exception:
                        pass
            
            GLib.idle_add(apply_ui_updates)
            
        threading.Thread(target=worker, daemon=True).start()
 
    def send_update_notification(self, count: int) -> None:
        app = self.get_application()
        notification = Gio.Notification.new("Updates Available")
        notification.set_body(f"There are {count} new application and system updates available.")
        notification.set_icon(Gio.ThemedIcon.new("system-software-update-symbolic"))
        notification.set_default_action("app.show-window")
        app.send_notification("updates-available", notification)



    def periodic_check_updates(self) -> bool:
        if not self.spinner.get_visible():
            self.check_for_updates()
        return True
