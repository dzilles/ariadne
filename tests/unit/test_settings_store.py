import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ariadne.application import settings_store


def test_update_user_setting_persists_single_value(tmp_path, monkeypatch):
    settings_file = tmp_path / "user_settings.json"
    monkeypatch.setattr(settings_store, "SETTINGS_DIR", str(tmp_path))
    monkeypatch.setattr(settings_store, "SETTINGS_FILE", str(settings_file))

    assert settings_store.update_user_setting("verbose", True)

    assert settings_store.load_user_settings() == {"verbose": True}
