import os
import json

CONFIG_DIR = ".ariadne"
SETTINGS_FILE = os.path.join(CONFIG_DIR, "user_settings.json")

def init_config():
    # Create config directory if it doesn't exist
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
        print(f"\033[92mCreated directory: {CONFIG_DIR}\033[0m")
    else:
        print(f"\033[93mDirectory already exists: {CONFIG_DIR}\033[0m")

    # Default settings
    default_settings = {
        "llm_backend": "gemini",
        "model": "gemini-3-flash-preview",
        "project_path": ".",
        "verbose": False,
        "tool_approval": True,
        "sandbox_mode": True
    }

    # Create user_settings.json if it doesn't exist
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w") as f:
            json.dump(default_settings, f, indent=2)
        print(f"\033[92mCreated default settings: {SETTINGS_FILE}\033[0m")
    else:
        print(f"\033[93mSettings file already exists: {SETTINGS_FILE}\033[0m")

    print(f"\033[96mNOTE: All API Keys must be configured securely using the '/secret' command in the TUI.\033[0m")

if __name__ == "__main__":
    init_config()
