from types import SimpleNamespace

from src.ariadne.policies import registry


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
