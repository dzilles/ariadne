from types import SimpleNamespace

from src.ariadne.policies.defaults import DEFAULT_POLICY, READ_ONLY_TOOL_NAMES
from src.ariadne.policies import registry
from src.ariadne.policies.loader import _ensure_terminal_completion_tools


class FakeToolSource:
    def allowed_tool(self, work_item_id: str) -> str:
        """Allowed tool description."""
        return f"allowed {work_item_id}"

    def unconfigured_tool(self) -> str:
        """This tool should not appear in generated docs."""
        return "hidden"


def test_build_tool_docs_uses_resolved_policy_tools(monkeypatch):
    policy = SimpleNamespace(
        agents={
            "FakeAgent": SimpleNamespace(
                tools=["allowed_tool"],
            )
        }
    )
    monkeypatch.setattr(registry, "get_policy", lambda: policy)

    tools = registry.build_agent_tools("FakeAgent", [FakeToolSource()])
    docs = registry.build_tool_docs(tools)

    assert [tool.__name__ for tool in tools] == ["allowed_tool"]
    assert "`allowed_tool(work_item_id)`" in docs
    assert "Allowed tool description." in docs
    assert "unconfigured_tool" not in docs
    assert "This tool should not appear" not in docs


def test_orchestrator_policy_excludes_direct_mutation_and_merge_tools():
    tools = set(DEFAULT_POLICY["agents"]["Orchestrator"]["tools"])

    assert "write_file" not in tools
    assert "edit_file" not in tools
    assert "execute_command" not in tools
    assert "run_shell_command" not in tools
    assert "force_merge" not in tools


def test_read_only_tools_do_not_require_permission_or_work_item_context():
    policies = DEFAULT_POLICY["tools"]

    for tool_name in READ_ONLY_TOOL_NAMES:
        checks = set(policies[tool_name]["checks"])
        assert "user_permission" not in checks
        assert "work_item_state" not in checks
        assert "work_item_transition" not in checks
        assert "work_item_field" not in checks


def test_completion_tool_is_available_to_delegated_agents_only():
    for agent_name, policy in DEFAULT_POLICY["agents"].items():
        tools = set(policy["tools"])
        if agent_name == "Orchestrator":
            assert "return_to_orchestrator" not in tools
            assert "finish_agent_run" not in tools
        else:
            assert "return_to_orchestrator" in tools
            assert "finish_agent_run" in tools

    for tool_name in ("return_to_orchestrator", "finish_agent_run"):
        completion_policy = DEFAULT_POLICY["tools"][tool_name]
        assert completion_policy["checks"] == []
        assert completion_policy["return_direct"] is True


def test_older_policy_overrides_keep_required_terminal_tools():
    policy = {
        "agents": {
            "Requirements": {
                "tools": ["get_work_item", "finish_agent_run"],
            }
        }
    }

    _ensure_terminal_completion_tools(policy)

    assert policy["agents"]["Requirements"]["tools"] == [
        "get_work_item",
        "return_to_orchestrator",
        "finish_agent_run",
    ]
