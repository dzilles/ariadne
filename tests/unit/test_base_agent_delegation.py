import pytest

from src.ariadne.agents.base_agent import BaseAgent


class FailingExecutor:
    def invoke(self, inputs):
        raise RuntimeError("provider unavailable")


def _agent(*, propagate_errors):
    agent = BaseAgent.__new__(BaseAgent)
    agent.chat_history = []
    agent.agent_executor = FailingExecutor()
    agent._propagate_delegation_errors = propagate_errors
    return agent


def test_delegated_agent_propagates_execution_error_to_coordinator():
    agent = _agent(propagate_errors=True)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        agent.chat("run delegated task")


def test_interactive_agent_keeps_error_response_behavior():
    agent = _agent(propagate_errors=False)

    result = agent.chat("run interactive task")

    assert result == "[System Error: provider unavailable]"
