import json

import src.ariadne.application.history as history_module
from src.ariadne.application.history import load_history, save_history


class ContextAgent:
    def __init__(self):
        self.context = {
            "schema_version": 2,
            "system_message": "system",
            "current_prompt": "system\n\nmission",
            "chat_history": [{"type": "human", "data": {"content": "hello"}}],
        }
        self.loaded = None

    def get_context(self):
        return self.context

    def load_context(self, context):
        self.loaded = context


def test_save_history_writes_full_agent_context(tmp_path, monkeypatch):
    monkeypatch.setattr(history_module, "HISTORY_DIR", str(tmp_path))
    agent = ContextAgent()

    assert save_history(agent, "Requirements") is True

    saved = json.loads((tmp_path / "chat_history_requirements.json").read_text())
    assert saved["system_message"] == "system"
    assert saved["current_prompt"] == "system\n\nmission"
    assert saved["chat_history"][0]["data"]["content"] == "hello"


def test_load_history_restores_full_agent_context(tmp_path, monkeypatch):
    monkeypatch.setattr(history_module, "HISTORY_DIR", str(tmp_path))
    payload = {
        "schema_version": 2,
        "system_message": "system",
        "current_prompt": "system\n\nmission",
        "chat_history": [],
    }
    (tmp_path / "chat_history_developer.json").write_text(json.dumps(payload))
    agent = ContextAgent()

    assert load_history(agent, "Developer") is True

    assert agent.loaded == payload
