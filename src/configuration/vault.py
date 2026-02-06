import keyring
import logging
import platform

logger = logging.getLogger(__name__)

SERVICE_NAME = "ariadne_autonomous_engine"

class Vault:
    """
    Wrapper around system keyring for secure secret storage.
    """
    
    @staticmethod
    def get_secret(key: str) -> str:
        """Retrieve a secret from the OS keyring."""
        try:
            return keyring.get_password(SERVICE_NAME, key)
        except Exception as e:
            logger.warning(f"Could not retrieve {key} from keyring: {e}")
            return None

    @staticmethod
    def set_secret(key: str, value: str):
        """Save a secret to the OS keyring."""
        try:
            keyring.set_password(SERVICE_NAME, key, value)
            logger.info(f"Securely saved {key} to system vault.")
        except Exception as e:
            logger.error(f"Failed to save {key} to keyring: {e}")
            raise

    @staticmethod
    def delete_secret(key: str):
        """Remove a secret from the OS keyring."""
        try:
            keyring.delete_password(SERVICE_NAME, key)
            logger.info(f"Deleted {key} from system vault.")
        except Exception as e:
            logger.warning(f"Failed to delete {key} from keyring (might not exist): {e}")

    @staticmethod
    def list_managed_keys():
        """
        Note: Standard keyring API does not support listing keys easily across all platforms.
        We return a list of known keys we manage.
        """
        return [
            "LLM_API_KEY",
            "PLANE_API_TOKEN",
            "PO_AGENT_API_KEY",
            "REQUIREMENTS_AGENT_API_KEY",
            "ENGINEER_AGENT_API_KEY",
            "DEV_AGENT_API_KEY",
            "QA_AGENT_API_KEY"
        ]
