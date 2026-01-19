import os
import glob
import csv
from dotenv import load_dotenv

def load_configuration():
    # 1. Load environment variables from .config/.env
    config_path = os.path.join(os.getcwd(), ".config", ".env")
    load_dotenv(config_path)

    config = {
        "PLANE_URL": os.getenv("PLANE_URL", "http://localhost:8090"),
        "LLM_BACKEND": os.getenv("LLM_BACKEND", "ollama"),
        "PLANE_API_TOKEN": None
    }

    # 2. Find and read the Plane secret key file
    plane_dir = os.path.join(os.getcwd(), ".plane")
    secret_files = glob.glob(os.path.join(plane_dir, "secret-key-*.csv"))

    if not secret_files:
        print("Warning: No Plane secret key file found in .plane/")
        return config

    # Use the most recent file if multiple exist
    latest_secret_file = max(secret_files, key=os.path.getctime)

    try:
        with open(latest_secret_file, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Assuming the token we want is the "Main access token" or just the first one
                if "Secret key" in row and row["Secret key"]:
                    config["PLANE_API_TOKEN"] = row["Secret key"]
                    break
    except Exception as e:
        print(f"Error reading Plane secret key: {e}")

    return config

# Singleton configuration object
settings = load_configuration()
