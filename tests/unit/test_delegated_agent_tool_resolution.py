from src.ariadne.agents.architect_agent import ArchitectAgent
from src.ariadne.agents.base_agent import BaseAgent
from src.ariadne.agents.developer_agent import DeveloperAgent
from src.ariadne.agents.qa_agent import QualityAssuranceAgent
from src.ariadne.agents.qm_agent import QMAgent
from src.ariadne.agents.requirements_agent import RequirementsAgent
from src.ariadne.agents.tester_agent import TesterAgent as AriadneTesterAgent


def _tool_names(agent):
    return [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in agent.tools]


def _tool_func(tool):
    return getattr(tool, "func", tool)


class FakeAgentRunTools:
    def return_to_orchestrator(self):
        """Typed agent completion handoff."""
        return "orchestrator"

    def finish_agent_run(self):
        """Compatibility agent completion handoff."""
        return "agent-run"


class FakeWorkItemTools:
    def __getattr__(self, name):
        def tool(*args, **kwargs):
            return f"work-item:{name}"

        tool.__name__ = name
        tool.__doc__ = f"Fake work item tool {name}."
        return tool

    def finish_agent_run(self):
        """Wrong persistence helper for delegated agents."""
        return "work-item"


class FakeFileTools:
    def __getattr__(self, name):
        def tool(*args, **kwargs):
            return f"file:{name}"

        tool.__name__ = name
        tool.__doc__ = f"Fake file tool {name}."
        return tool


class FakeGitTools:
    def __getattr__(self, name):
        def tool(*args, **kwargs):
            return f"git:{name}"

        tool.__name__ = name
        tool.__doc__ = f"Fake git tool {name}."
        return tool


class FakeShellTools:
    def run_shell_command(self):
        """Run a shell command."""
        return "shell"


def test_delegated_agents_resolve_terminal_tools_to_completion_recorder(monkeypatch):
    monkeypatch.setattr(BaseAgent, "__init__", lambda self: None)
    monkeypatch.setattr(
        BaseAgent,
        "_init_executor",
        lambda self, tools, system_message: setattr(self, "tools", tools),
    )

    work_item_tools = FakeWorkItemTools()
    file_tools = FakeFileTools()
    git_tools = FakeGitTools()
    shell_tools = FakeShellTools()
    agent_run_tools = FakeAgentRunTools()

    agents = [
        RequirementsAgent(work_item_tools, file_tools, git_tools, agent_run_tools),
        QMAgent(work_item_tools, file_tools, agent_run_tools),
        ArchitectAgent(work_item_tools, file_tools, git_tools, shell_tools, agent_run_tools),
        DeveloperAgent(work_item_tools, file_tools, git_tools, shell_tools, agent_run_tools),
        AriadneTesterAgent(work_item_tools, file_tools, git_tools, shell_tools, agent_run_tools),
        QualityAssuranceAgent(work_item_tools, file_tools, agent_run_tools),
    ]

    for agent in agents:
        tools = _tool_names(agent)
        assert "return_to_orchestrator" in tools
        assert "finish_agent_run" in tools
        return_tool = agent.tools[tools.index("return_to_orchestrator")]
        finish_tool = agent.tools[tools.index("finish_agent_run")]
        assert _tool_func(return_tool)() == "orchestrator"
        assert _tool_func(finish_tool)() == "agent-run"
