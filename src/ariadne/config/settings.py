import logging
import json
import os
from typing import Any, Dict, List, Tuple
from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict, PydanticBaseSettingsSource
from src.ariadne.config.vault import Vault

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

        extra="ignore",

        populate_by_name=True

    )



    llm_backend: str = "gemini"

    project_path: str = Field(".", validation_alias="ARIADNE_PROJECT_PATH")

    

    # LLM Configuration (non-secret)

    model: str = Field(default="gemini-3-flash-preview", validation_alias="MODEL")



    # UI Settings

    verbose: bool = Field(default=False, description="Enable verbose output")

    tool_approval: bool = Field(default=True, description="Require approval for tool execution")

    tool_audit_enabled: bool = Field(default=True, description="Automatically append configured tool calls to the active work item log")

    tool_audit_logged_tools: List[str] = Field(
        default_factory=lambda: [
            "write_file",
            "run_shell_command",
            "commit_changes",
            "update_status",
            "approve_gate",
            "reject_gate",
            "add_link",
            "add_commit_hash",
            "update_git_metadata",
            "delegate_to_agent",
        ],
        description="Tool names that should be logged to the active work item"
    )

    tool_audit_logged_statuses: List[str] = Field(
        default_factory=lambda: ["success", "error", "cancelled"],
        description="Tool execution statuses that should be logged to the active work item"
    )

    tool_audit_result_max_chars: int = Field(default=1000, description="Maximum result characters stored per tool audit log entry")

    

    # Sandbox Settings

    sandbox_mode: bool = Field(default=True, description="Run file/git/shell operations in an isolated Docker container")

    sandbox_dir: str = Field(default=".ariadne/sandbox/workspace", description="Local path to the sandbox workspace")



    @classmethod

    def settings_customise_sources(

        cls,

        settings_cls: type[BaseSettings],

        init_settings: PydanticBaseSettingsSource,

        env_settings: PydanticBaseSettingsSource,

        dotenv_settings: PydanticBaseSettingsSource, # This will now be empty/ignored

        file_secret_settings: PydanticBaseSettingsSource,

    ) -> Tuple[PydanticBaseSettingsSource, ...]:

        return (

            init_settings,

            VaultSettingsSource(settings_cls),

            JsonConfigSettingsSource(settings_cls),

            env_settings,

        )



settings = Settings()
