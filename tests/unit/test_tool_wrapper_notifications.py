import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ariadne.runtime.context import set_active_work_item_id
from src.ariadne.runtime import run_manager
from src.ariadne.tools import tool_wrapper


class FakeApprovalFuture:
    def __init__(self, result="yes", done=False):
        self._result = result
        self._done = done
        self.cancelled = False

    def done(self):
        return self._done

    def result(self):
        return self._result

    def cancel(self):
        self.cancelled = True


class ImmediateLoop:
    def call_soon_threadsafe(self, callback):
        callback()


def test_notify_tool_emits_structured_notification(monkeypatch):
    notifications = []
    monkeypatch.setattr(tool_wrapper, "_tool_notify_callback", notifications.append)
    monkeypatch.setattr(tool_wrapper, "_event_loop", ImmediateLoop())

    tool_wrapper._notify_tool("read_file", "success", {"path": "a.txt"}, "ok")

    assert notifications[0].name == "read_file"
    assert notifications[0].status == "success"
    assert notifications[0].args == {"path": "a.txt"}
    assert notifications[0].result == "ok"


def test_wrapped_tool_notification_serializes_positional_args(monkeypatch):
    notifications = []
    monkeypatch.setattr(tool_wrapper, "_tool_notify_callback", notifications.append)
    monkeypatch.setattr(tool_wrapper, "_event_loop", ImmediateLoop())
    monkeypatch.setattr(tool_wrapper, "_approval_callback", None)
    monkeypatch.setattr(tool_wrapper, "_approval_enabled", False)

    def read_file(file_path):
        return f"read {file_path}"

    wrapped = tool_wrapper.with_error_handling(read_file)

    wrapped("README.md")

    assert notifications[0].status == "start"
    assert notifications[0].args == {"args": ["README.md"]}
    assert notifications[1].status == "success"
    assert notifications[1].args == {"args": ["README.md"]}


def test_generally_allowed_tool_does_not_request_approval(monkeypatch):
    approval_requests = []
    monkeypatch.setattr(tool_wrapper, "_tool_notify_callback", lambda notification: None)
    monkeypatch.setattr(tool_wrapper, "_event_loop", ImmediateLoop())
    monkeypatch.setattr(tool_wrapper, "_approval_callback", object())
    monkeypatch.setattr(tool_wrapper, "_approval_enabled", True)
    monkeypatch.setattr(tool_wrapper, "_auto_approve_session", False)

    def reject_approval(tool_name, args, ignore_session_approval=False):
        approval_requests.append((tool_name, args, ignore_session_approval))
        return False

    monkeypatch.setattr(tool_wrapper, "_request_approval_sync", reject_approval)

    def read_file(file_path):
        return f"read {file_path}"

    wrapped = tool_wrapper.with_error_handling(read_file)

    result = wrapped("README.md")

    assert result == "read README.md"
    assert approval_requests == []


def test_rejected_user_permission_tool_notifies_cancelled_and_returns_feedback(monkeypatch):
    notifications = []
    approval_requests = []
    monkeypatch.setattr(tool_wrapper, "_tool_notify_callback", notifications.append)
    monkeypatch.setattr(tool_wrapper, "_event_loop", ImmediateLoop())
    monkeypatch.setattr(tool_wrapper, "_approval_callback", object())
    monkeypatch.setattr(tool_wrapper, "_approval_enabled", True)
    monkeypatch.setattr(tool_wrapper, "_auto_approve_session", False)

    def reject_approval(tool_name, args, ignore_session_approval=False):
        approval_requests.append((tool_name, args, ignore_session_approval))
        return False

    monkeypatch.setattr(tool_wrapper, "_request_approval_sync", reject_approval)

    def delegate_to_agent(agent_name, work_item_id, task_description):
        return f"delegated {work_item_id}"

    wrapped = tool_wrapper.with_error_handling(delegate_to_agent)

    result = wrapped("Developer", "1", "Build it")

    assert result == "[Tool Cancelled: delegate_to_agent] User rejected the operation."
    assert approval_requests == [
        (
            "delegate_to_agent",
            {"args": ["Developer", "1", "Build it"]},
            True,
        )
    ]
    assert notifications[0].status == "cancelled"
    assert notifications[0].args == {"args": ["Developer", "1", "Build it"]}


def test_mixed_user_and_state_policy_requires_both_before_execution(monkeypatch):
    notifications = []
    approval_requests = []
    store = SimpleNamespace(
        get_work_item=lambda work_item_id: SimpleNamespace(
            id=work_item_id,
            status="Ready for Development",
        )
    )
    monkeypatch.setattr(
        "src.ariadne.infrastructure.container.DependencyRegistry.get_work_item_tools",
        lambda: SimpleNamespace(system=store),
    )
    monkeypatch.setattr(tool_wrapper, "_tool_notify_callback", notifications.append)
    monkeypatch.setattr(tool_wrapper, "_event_loop", ImmediateLoop())
    monkeypatch.setattr(tool_wrapper, "_approval_callback", object())
    monkeypatch.setattr(tool_wrapper, "_approval_enabled", True)
    monkeypatch.setattr(tool_wrapper, "_auto_approve_session", False)

    def approve(tool_name, args, ignore_session_approval=False):
        approval_requests.append((tool_name, args, ignore_session_approval))
        return True

    monkeypatch.setattr(tool_wrapper, "_request_approval_sync", approve)

    def write_file(file_path, content):
        return f"wrote {file_path}"

    set_active_work_item_id("7")
    try:
        wrapped = tool_wrapper.with_error_handling(write_file)

        result = wrapped("demo.txt", "content")
    finally:
        set_active_work_item_id(None)

    assert result == "wrote demo.txt"
    assert approval_requests == [("write_file", {"args": ["demo.txt", "content"]}, False)]
    assert [notification.status for notification in notifications] == ["start", "success"]


def test_state_policy_blocks_before_user_approval(monkeypatch):
    approval_requests = []
    monkeypatch.setattr(tool_wrapper, "_tool_notify_callback", lambda notification: None)
    monkeypatch.setattr(tool_wrapper, "_event_loop", ImmediateLoop())
    monkeypatch.setattr(tool_wrapper, "_approval_callback", object())
    monkeypatch.setattr(tool_wrapper, "_approval_enabled", True)
    monkeypatch.setattr(tool_wrapper, "_auto_approve_session", False)

    def approve(tool_name, args, ignore_session_approval=False):
        approval_requests.append((tool_name, args, ignore_session_approval))
        return True

    monkeypatch.setattr(tool_wrapper, "_request_approval_sync", approve)

    def write_file(file_path, content):
        return f"wrote {file_path}"

    wrapped = tool_wrapper.with_error_handling(write_file)

    result = wrapped("demo.txt", "content")

    assert result.startswith("⛔ BLOCK:")
    assert approval_requests == []


def test_approval_wait_returns_no_when_cancel_requested():
    approval_future = FakeApprovalFuture(done=False)
    run = run_manager.start_run("Fake", "hello")
    run_manager.request_cancel()

    try:
        result = tool_wrapper._wait_for_approval_result(approval_future, "read_file")
    finally:
        run_manager.finish_run(run.id)

    assert result == "no"
    assert approval_future.cancelled is True


def test_approval_wait_times_out_closed(monkeypatch):
    approval_future = FakeApprovalFuture(done=False)
    monkeypatch.setattr(tool_wrapper, "APPROVAL_TIMEOUT_SECONDS", 0)

    result = tool_wrapper._wait_for_approval_result(approval_future, "read_file")

    assert result == "no"
    assert approval_future.cancelled is True


def test_cancel_requested_before_tool_notifies_cancelled(monkeypatch):
    notifications = []
    monkeypatch.setattr(tool_wrapper, "_tool_notify_callback", notifications.append)
    monkeypatch.setattr(tool_wrapper, "_event_loop", ImmediateLoop())
    monkeypatch.setattr(tool_wrapper, "_approval_callback", None)
    monkeypatch.setattr(tool_wrapper, "_approval_enabled", False)
    run = run_manager.start_run("Fake", "hello")
    run_manager.request_cancel()

    def read_file(file_path):
        return f"read {file_path}"

    try:
        wrapped = tool_wrapper.with_error_handling(read_file)

        result = wrapped("README.md")
    finally:
        run_manager.finish_run(run.id)

    assert result == "[Tool Cancelled: read_file] Run cancellation requested by user."
    assert notifications[0].status == "cancelled"
    assert notifications[0].args == {"args": ["README.md"]}


def test_return_direct_policy_wraps_callable_as_structured_tool(monkeypatch):
    monkeypatch.setattr(
        tool_wrapper,
        "_is_tool_return_direct",
        lambda name: name == "finish_agent_run",
    )
    monkeypatch.setattr(tool_wrapper, "_approval_callback", None)
    monkeypatch.setattr(tool_wrapper, "_approval_enabled", False)

    def finish_agent_run(status: str, comment: str) -> str:
        """Finish the delegated run."""
        return f"[{status}] {comment}"

    wrapped = tool_wrapper.wrap_tools_with_error_handling([finish_agent_run])

    assert wrapped[0].name == "finish_agent_run"
    assert wrapped[0].return_direct is True
    assert wrapped[0].invoke({"status": "SUCCESS", "comment": "Done"}) == "[SUCCESS] Done"
