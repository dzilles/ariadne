import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.ariadne.application.controller as controller_module
from src.ariadne.application.controller import AriadneApplicationController
from src.ariadne.application.ui_contract import RunEvent, WorkItemInfo
from src.ariadne.tools.tool_wrapper import ToolNotification


class FakeAgent:
    def __init__(self):
        self.cleared = False

    def get_history(self):
        return []

    def load_history(self, history):
        self.loaded_history = history

    def clear_history(self):
        self.cleared = True


def test_load_chat_history_reports_loaded_count(monkeypatch):
    monkeypatch.setattr(controller_module, "load_history", lambda agent, name: True)
    monkeypatch.setattr(
        controller_module,
        "get_history_summary",
        lambda name: {"message_count": 3},
    )

    controller = AriadneApplicationController(
        {"Fake": FakeAgent},
        {"Fake": "fake agent"},
        reset_session_approval_func=lambda: None,
    )
    controller.switch_agent("Fake")

    result = controller.load_chat_history()

    assert not result.is_error
    assert result.message == "Loaded 3 messages for **Fake**"


def test_history_status_lists_registered_agents(monkeypatch):
    monkeypatch.setattr(controller_module, "get_history_summary", lambda name: None)

    controller = AriadneApplicationController(
        {"Fake": FakeAgent},
        {"Fake": "fake agent"},
        reset_session_approval_func=lambda: None,
    )
    controller.switch_agent("Fake")

    result = controller.get_history_status()

    assert not result.is_error
    assert "`Fake` (active): No saved history" in result.message


def test_clear_chat_history_uses_existing_history_function(monkeypatch):
    monkeypatch.setattr(controller_module, "clear_history", lambda name: True)

    controller = AriadneApplicationController(
        {"Fake": FakeAgent},
        {"Fake": "fake agent"},
        reset_session_approval_func=lambda: None,
    )
    controller.switch_agent("Fake")
    agent = controller.current_agent

    result = controller.clear_chat_history()

    assert not result.is_error
    assert result.message == "History cleared for **Fake**"
    assert agent.cleared is True


def test_tool_event_translation_refreshes_active_work_item(monkeypatch):
    controller = AriadneApplicationController(
        {"Fake": FakeAgent},
        {"Fake": "fake agent"},
        reset_session_approval_func=lambda: None,
    )
    tool_events = []
    work_items = []
    controller._tool_event_callback = tool_events.append
    controller._active_work_item_callback = work_items.append
    controller.set_active_work_item_id("7")
    monkeypatch.setattr(
        controller,
        "get_active_work_item_info",
        lambda: WorkItemInfo("7", "Demo", "In Progress"),
    )

    controller._handle_tool_notify(
        ToolNotification("list_work_items", "success", {"limit": 5}, "ok")
    )

    assert tool_events[0].name == "list_work_items"
    assert tool_events[0].status == "success"
    assert tool_events[0].args == {"limit": 5}
    assert tool_events[0].result == "ok"
    assert work_items == [WorkItemInfo("7", "Demo", "In Progress")]


def test_active_work_item_id_change_emits_display_info(monkeypatch):
    controller = AriadneApplicationController(
        {"Fake": FakeAgent},
        {"Fake": "fake agent"},
        reset_session_approval_func=lambda: None,
    )
    work_items = []
    controller._active_work_item_callback = work_items.append
    monkeypatch.setattr(
        controller,
        "get_active_work_item_info",
        lambda: WorkItemInfo("9", "Build UI", "Open"),
    )

    controller._handle_active_work_item_changed("9")

    assert controller.has_active_work_item()
    assert work_items == [WorkItemInfo("9", "Build UI", "Open")]


def test_token_usage_translation_uses_contract_type():
    controller = AriadneApplicationController(
        {"Fake": FakeAgent},
        {"Fake": "fake agent"},
        reset_session_approval_func=lambda: None,
    )
    usages = []
    controller._token_usage_callback = usages.append

    controller._handle_token_usage(
        {"input_tokens": 11, "output_tokens": 13, "total_tokens": 24}
    )

    assert usages[0].input_tokens == 11
    assert usages[0].output_tokens == 13
    assert usages[0].total_tokens == 24


def test_handle_user_message_without_agent_emits_error_event():
    controller = AriadneApplicationController(
        {"Fake": FakeAgent},
        {"Fake": "fake agent"},
        reset_session_approval_func=lambda: None,
    )
    events = []

    asyncio.run(
        controller.handle_user_message(
            "hello",
            emit=events.append,
            is_cancelled=lambda: False,
        )
    )

    assert events == [
        RunEvent("error", message="No agent selected. Use /agent to select one.")
    ]
