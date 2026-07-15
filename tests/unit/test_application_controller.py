import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.ariadne.application.controller as controller_module
from src.ariadne.application.controller import AriadneApplicationController
from src.ariadne.application.ui_contract import RunEvent, WorkItemInfo
from src.ariadne.runtime import run_manager
from src.ariadne.tools.tool_wrapper import ToolNotification


class FakeAgent:
    def __init__(self):
        self.cleared = False
        self.loaded_context = None

    def get_history(self):
        return []

    def get_context(self):
        return {
            "schema_version": 2,
            "system_message": "system",
            "current_prompt": "prompt",
            "chat_history": [],
        }

    def load_history(self, history):
        self.loaded_history = history

    def load_context(self, context):
        self.loaded_context = context

    def clear_history(self):
        self.cleared = True


class FakeOrchestrator(FakeAgent):
    def __init__(self):
        super().__init__()
        self.delegations = []

    def delegate_to_agent(self, agent_name, work_item_id, task_description):
        self.delegations.append((agent_name, work_item_id, task_description))
        return "coordinated specialist result"


def test_load_chat_history_loads_all_agent_contexts(monkeypatch):
    loaded = []

    def fake_load(agent, name):
        loaded.append(name)
        agent.load_context({"current_prompt": f"prompt {name}", "chat_history": []})
        return True

    monkeypatch.setattr(controller_module, "load_history", fake_load)

    controller = AriadneApplicationController(
        {"Fake": FakeAgent, "Other": FakeAgent},
        {"Fake": "fake agent", "Other": "other agent"},
        reset_session_approval_func=lambda: None,
    )
    controller.switch_agent("Fake")

    result = controller.load_chat_history()

    assert not result.is_error
    assert result.message == "Loaded contexts for 2 agent(s)."
    assert set(loaded) == {"Fake", "Other"}
    assert controller._agent_instances["Other"].loaded_context["current_prompt"] == "prompt Other"


def test_save_chat_history_saves_all_agent_contexts(monkeypatch):
    saved = []
    monkeypatch.setattr(
        controller_module,
        "save_history",
        lambda agent, name: saved.append(name) or True,
    )

    controller = AriadneApplicationController(
        {"Fake": FakeAgent, "Other": FakeAgent},
        {"Fake": "fake agent", "Other": "other agent"},
        reset_session_approval_func=lambda: None,
    )
    controller.switch_agent("Fake")

    result = controller.save_chat_history()

    assert not result.is_error
    assert result.message == "Saved contexts for 2 agent(s)."
    assert set(saved) == {"Fake", "Other"}


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
    assert "`Fake` (active): No saved context" in result.message


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
    assert result.message == "Context cleared for **Fake**"
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


def test_selected_specialist_requires_active_work_item():
    controller = AriadneApplicationController(
        {"Orchestrator": FakeOrchestrator, "Requirements": FakeAgent},
        {"Orchestrator": "coordinator", "Requirements": "specialist"},
        reset_session_approval_func=lambda: None,
    )
    controller.switch_agent("Requirements")
    events = []

    asyncio.run(
        controller.handle_user_message(
            "Write requirements.",
            emit=events.append,
            is_cancelled=lambda: False,
        )
    )

    assert events == [
        RunEvent(
            "error",
            message="Select or activate a work item before running a specialist agent.",
        )
    ]
    assert controller.current_agent_name == "Requirements"


def test_selected_specialist_runs_through_orchestrator_and_returns_control(monkeypatch):
    monkeypatch.setattr(controller_module, "save_history", lambda agent, name: True)
    controller = AriadneApplicationController(
        {"Orchestrator": FakeOrchestrator, "Requirements": FakeAgent},
        {"Orchestrator": "coordinator", "Requirements": "specialist"},
        reset_session_approval_func=lambda: None,
    )
    controller.switch_agent("Requirements")
    controller.set_active_work_item_id("17")
    events = []

    asyncio.run(
        controller.handle_user_message(
            "Write requirements.",
            emit=events.append,
            is_cancelled=lambda: False,
        )
    )

    orchestrator = controller.current_agent
    assert controller.current_agent_name == "Orchestrator"
    assert orchestrator.delegations == [
        ("Requirements", "17", "Write requirements.")
    ]
    assert any(
        event.type == "complete" and event.message == "coordinated specialist result"
        for event in events
    )


def test_handle_user_message_queues_when_run_is_active():
    controller = AriadneApplicationController(
        {"Fake": FakeAgent},
        {"Fake": "fake agent"},
        reset_session_approval_func=lambda: None,
    )
    events = []
    run = run_manager.start_run("Fake", "active")

    try:
        asyncio.run(
            controller.handle_user_message(
                "queued",
                emit=events.append,
                is_cancelled=lambda: False,
            )
        )
    finally:
        run_manager.finish_run(run.id)

    assert len(controller._message_queue) == 1
    assert controller._message_queue[0].message == "queued"
    assert events == [
        RunEvent(
            "queued",
            detail="Queued. This message will run after the active request. Position: 1.",
        )
    ]
