import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import dotenv_values
from src.configuration.vault import Vault

CONFIG_DIR = ".ariadne"
ENV_FILE = os.path.join(CONFIG_DIR, ".env")

SENSITIVE_KEYS = [
    "PLANE_API_KEY", 
    "PLANE_API_TOKEN",
    "PO_AGENT_API_KEY",
    "REQUIREMENTS_AGENT_API_KEY",
    "ARCHITECT_AGENT_API_KEY",
    "DEVELOPER_AGENT_API_KEY",
    "TESTER_AGENT_API_KEY",
    "QA_AGENT_API_KEY",
    "ORCHESTRATOR_AGENT_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "SECRET_KEY"
]

def migrate_secrets():
    print(f"Migrating secrets from {ENV_FILE} to System Vault...")
    
    if not os.path.exists(ENV_FILE):
        print("No .env file found.")
        return

    # Load all values (without parsing/exporting to env)
    config = dotenv_values(ENV_FILE)
    
    keys_moved = 0
    remaining_config = {}

    for key, value in config.items():
        if not value:
            continue
            
        # Check if key is sensitive
        is_sensitive = key in SENSITIVE_KEYS or key.endswith("_KEY") or key.endswith("_TOKEN")
        
        if is_sensitive:
            print(f"  -> Moving {key} to Vault...")
            try:
                Vault.set_secret(key, value)
                keys_moved += 1
            except Exception as e:
                print(f"  [ERROR] Failed to save {key}: {e}")
                remaining_config[key] = value # Keep in file if fail
        else:
            remaining_config[key] = value

    if keys_moved > 0:
        print(f"\nSuccessfully moved {keys_moved} secrets to Vault.")
        print("Rewriting .env file without secrets...")
        
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            for key, value in remaining_config.items():
                f.write(f"{key}={value}\n")
        
        print("Migration Complete.")
    else:
        print("No sensitive keys found to migrate.")

if __name__ == "__main__":
    migrate_secrets()
