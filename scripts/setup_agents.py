import os
import sys

# Constants
CONFIG_DIR = ".config"
ENV_FILE = os.path.join(CONFIG_DIR, ".env")
AGENTS = ["PO_AGENT", "ENGINEER_AGENT", "DEV_AGENT", "QA_AGENT"]

def setup_agent_keys():
    print("==========================================")
    print("      Ariadne Agent API Key Setup")
    print("==========================================\n")
    
    print("Currently, Plane does not allow programmatically creating API keys via the API.")
    print("You will need to manually create 4 API tokens for your agents.")
    print("\nINSTRUCTIONS:")
    print("1. Go to your Plane instance: http://localhost:8090/settings/profile")
    print("   (Or click on your Profile Picture -> Settings -> API Tokens)")
    print("2. Create a new token for each agent below.")
    print("3. Paste the tokens when prompted.\n")

    new_keys = {}

    for agent in AGENTS:
        env_var = f"{agent}_API_KEY"
        current_val = os.getenv(env_var)
        
        prompt = f"Enter API Token for {agent}"
        if current_val:
            prompt += f" (Current: {current_val[:4]}...)"
        
        val = input(f"{prompt}: ").strip()
        
        if val:
            new_keys[env_var] = val
        elif not val and not current_val:
            print(f"Skipping {agent} (Will use default/admin key).")
        else:
            print(f"Keeping existing key for {agent}.")

    if not new_keys:
        print("\nNo new keys provided. Exiting.")
        return

    # Read existing .env
    existing_lines = []
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            existing_lines = f.readlines()

    # Update or Append keys
    with open(ENV_FILE, "w") as f:
        # Write existing lines, skipping the ones we are updating
        for line in existing_lines:
            key = line.split("=")[0].strip()
            if key not in new_keys:
                f.write(line)
        
        # Append new keys
        f.write("\n\n# Agent API Keys\n")
        for key, value in new_keys.items():
            f.write(f"{key}={value}\n")
            print(f"Saved {key}")

    print(f"\nSuccess! Agent keys saved to {ENV_FILE}")

if __name__ == "__main__":
    setup_agent_keys()
