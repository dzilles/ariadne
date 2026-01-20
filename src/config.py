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
        "PROJECT_PATH": os.getenv("ARIADNE_PROJECT_PATH", "."),
        "PLANE_API_TOKEN": None
    }

    # 2. Find and read the Plane secret key file
    search_dirs = [
        os.path.join(os.getcwd(), ".plane"),
        os.path.join(os.getcwd(), ".config")
    ]
    
    secret_files = []
    for d in search_dirs:
        if os.path.exists(d):
            secret_files.extend(glob.glob(os.path.join(d, "secret-key-*.csv")))

    if not secret_files:
        logger.warning("No Plane secret key file found in .plane/ or .config/")
    else:
        # Use the most recent file if multiple exist
        latest_secret_file = max(secret_files, key=os.path.getctime)
        logger.info(f"Loading Plane API key from {latest_secret_file}")

        try:
            with open(latest_secret_file, "r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Plane CSV usually has "Secret key" column
                    if "Secret key" in row and row["Secret key"]:
                        config["PLANE_API_TOKEN"] = row["Secret key"]
                        break
        except Exception as e:
            logger.error(f"Error reading Plane secret key: {e}")

    # Add other plane settings from env
    config["PLANE_WS_SLUG"] = os.getenv("PLANE_WS_SLUG")
    config["PLANE_PROJECT_ID"] = os.getenv("PLANE_PROJECT_ID")
    config["PLANE_API_URL"] = os.getenv("PLANE_API_URL", f"{config['PLANE_URL']}/api/v1")

    return config

# Configure logging for config loader if needed
import logging
logger = logging.getLogger(__name__)

# Singleton configuration object
settings = load_configuration()
