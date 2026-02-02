import os
import shutil

CONFIG_DIR = ".ariadne"
ENV_FILE = os.path.join(CONFIG_DIR, ".env")
EXAMPLE_ENV_FILE = os.path.join(CONFIG_DIR, ".env.example")

def init_config():
    # Create config directory if it doesn't exist
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
        print(f"\033[92mCreated directory: {CONFIG_DIR}\033[0m")
    else:
        print(f"\033[93mDirectory already exists: {CONFIG_DIR}\033[0m")

    # Create .env.example
    example_content = """# Plane Configuration
PLANE_API_URL=http://localhost:8091/api/v1
PLANE_API_KEY=your-plane-api-key
PLANE_WS_SLUG=your-workspace-slug
PLANE_PROJECT_ID=your-project-id

# LLM Configuration
LLM_PROVIDER=gemini
# Options: gemini, ollama

# Gemini Configuration
GOOGLE_API_KEY=your-google-api-key
GEMINI_MODEL=gemini-pro

# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# Project Path (Origin for agent file operations)
ARIADNE_PROJECT_PATH=.

# Agent API Keys
PO_AGENT_API_KEY=your-po-agent-key
ENGINEER_AGENT_API_KEY=your-engineer-agent-key
"""
    with open(EXAMPLE_ENV_FILE, "w") as f:
        f.write(example_content)
    print(f"\033[92mCreated example config: {EXAMPLE_ENV_FILE}\033[0m")

    # Create .env if it doesn't exist
    if not os.path.exists(ENV_FILE):
        shutil.copy(EXAMPLE_ENV_FILE, ENV_FILE)
        print(f"\033[92mCreated local config: {ENV_FILE}\033[0m")
        print(f"\033[96mACTION REQUIRED: Please update your Plane API key in {ENV_FILE}\033[0m")
    else:
        print(f"\033[93mLocal config already exists: {ENV_FILE}\033[0m")

if __name__ == "__main__":
    init_config()
