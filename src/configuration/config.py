import os
import glob
import csv
import logging
from typing import Optional, Any, Dict, Tuple
from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource
from src.configuration.vault import Vault

logger = logging.getLogger(__name__)

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
        extra="ignore"
    )

    plane_url: str = "http://localhost:8000"
    llm_backend: str = "gemini"
    project_path: str = Field(".", validation_alias="ARIADNE_PROJECT_PATH")
    
    plane_ws_slug: Optional[str] = Field(None, validation_alias="PLANE_WS_SLUG")
    plane_project_id: Optional[str] = Field(None, validation_alias="PLANE_PROJECT_ID")
    
    plane_api_token: Optional[str] = Field(None, validation_alias="PLANE_API_TOKEN")
    raw_plane_api_url: Optional[str] = Field(None, validation_alias="PLANE_API_URL")
    plane_api_rate_limit: str = Field(validation_alias="API_KEY_RATE_LIMIT")

    # Agent Specific Keys
    po_agent_api_key: Optional[str] = Field(None, validation_alias="PO_AGENT_API_KEY")
    requirements_agent_api_key: Optional[str] = Field(None, validation_alias="REQUIREMENTS_AGENT_API_KEY")
    engineer_agent_api_key: Optional[str] = Field(None, validation_alias="ENGINEER_AGENT_API_KEY")

    # LLM Keys
    google_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    ollama_model: Optional[str] = None

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
            VaultSettingsSource(settings_cls),
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    @property
    def plane_api_url(self) -> str:
        if self.raw_plane_api_url:
            return self.raw_plane_api_url
        return f"{self.plane_url}/api/v1"

    def model_post_init(self, __context):
        print(f"DEBUG INIT: google_api_key={self.google_api_key}")
        if not self.plane_api_token:
            self._load_token_from_csv()

    def _load_token_from_csv(self):
        search_dirs = [
            os.path.join(os.getcwd(), ".plane"),
            os.path.join(os.getcwd(), ".ariadne")
        ]
        secret_files = []
        for d in search_dirs:
            if os.path.exists(d):
                secret_files.extend(glob.glob(os.path.join(d, "secret-key-*.csv")))
        if not secret_files: return
        latest_secret_file = max(secret_files, key=os.path.getctime)
        try:
            with open(latest_secret_file, "r", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if "Secret key" in row and row["Secret key"]:
                        self.plane_api_token = row["Secret key"]
                        break
        except Exception: pass

settings = Settings()