import os
import json
from typing import Any, Dict

class SettingsManager:
    """Manages the settings and state serialization for App Updater."""
    
    def __init__(self) -> None:
        self.settings: Dict[str, Any] = self.load_settings()

    def load_settings(self) -> Dict[str, Any]:
        """Loads configuration from settings.json or returns default settings."""
        config_dir = os.path.expanduser("~/.config/app-updater")
        config_path = os.path.join(config_dir, "settings.json")
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading settings: {e}")
        return {
            "apt_enabled": True,
            "flatpak_enabled": True,
            "snap_enabled": True,
            "appimage_enabled": True
        }

    def save_settings(self) -> None:
        """Saves current configuration to settings.json."""
        config_dir = os.path.expanduser("~/.config/app-updater")
        config_path = os.path.join(config_dir, "settings.json")
        try:
            os.makedirs(config_dir, exist_ok=True)
            with open(config_path, 'w') as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def save_state(self, total_updates: int, updating: bool = False) -> None:
        """Saves current updates state to state.json for system tray updates."""
        config_dir = os.path.expanduser("~/.config/app-updater")
        os.makedirs(config_dir, exist_ok=True)
        state_path = os.path.join(config_dir, "state.json")
        try:
            with open(state_path, 'w') as f:
                json.dump({"total_updates": total_updates, "updating": updating}, f)
        except Exception as e:
            print(f"Error saving state: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Gets settings value for given key."""
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Sets settings value and triggers save."""
        self.settings[key] = value
        self.save_settings()
