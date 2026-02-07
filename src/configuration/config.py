import logging
import json
import os
from typing import Optional, Any, Dict, Tuple
from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource
from src.configuration.vault import Vault

logger = logging.getLogger(__name__)

class JsonConfigSettingsSource(PydanticBaseSettingsSource):
    """
    A custom settings source that loads configuration from .ariadne/user_settings.json.
    """
    def get_field_value(self, field: FieldInfo, field_name: str) -> Tuple[Any, str, bool]:
        # Not used directly in __call__ implementation below, but required by interface if we used standard logic
        return None, field_name, False

    def __call__(self) -> Dict[str, Any]:
        settings_path = os.path.join(".ariadne", "user_settings.json")
        if not os.path.exists(settings_path):
            return {}
        
        try:
            with open(settings_path, "r") as f:
                data = json.load(f)
            return data
        except Exception as e:
            logger.warning(f"Failed to load user settings from {settings_path}: {e}")
            return {}

class VaultSettingsSource(PydanticBaseSettingsSource):
    def get_field_value(self, field: FieldInfo, field_name: str) -> Tuple[Any, str, bool]:
        # Try upper case of field name (common for env vars/secrets)
        upper_name = field_name.upper()
        secret = Vault.get_secret(upper_name)
        if secret:
            return secret, upper_name, False
        
        # Try direct field name
        secret = Vault.get_secret(field_name)
        if secret:
            return secret, field_name, False
            
        return None, field_name, False

    def __call__(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        for field_name, field in self.settings_cls.model_fields.items():
            value, key, is_complex = self.get_field_value(field, field_name)
            if value is not None:
                d[field_name] = value
        return d

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".ariadne/.env", 
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True
    )

    plane_url: str = "http://localhost:8000"
    llm_backend: str = "gemini"
    project_path: str = Field(".", validation_alias="ARIADNE_PROJECT_PATH")
    
    plane_ws_slug: Optional[str] = Field(None, validation_alias="PLANE_WS_SLUG")
    plane_project_id: Optional[str] = Field(None, validation_alias="PLANE_PROJECT_ID")
    
    raw_plane_api_url: Optional[str] = Field(None, validation_alias="PLANE_API_URL")
    plane_api_rate_limit: Optional[str] = Field(None, validation_alias="API_KEY_RATE_LIMIT")

    # LLM Configuration (non-secret)
    model: Optional[str] = Field(None, validation_alias="MODEL")

    # TUI Configuration
    verbose: bool = Field(False, description="Enable verbose output mode")
    tool_approval: bool = Field(True, description="Require approval before tool calls")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            VaultSettingsSource(settings_cls),
            JsonConfigSettingsSource(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    @property
    def plane_api_url(self) -> str:
        if self.raw_plane_api_url:
            return self.raw_plane_api_url
        return f"{self.plane_url}/api/v1"

settings = Settings()