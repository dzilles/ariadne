from ariadne.configuration import ConfigurationStore, Configuration, Provider, Profile, Prompt
from ariadne.task.tools import tool_definitions as task_tools
from ariadne.configuration.tools import tool_definitions as config_tools
from ariadne._util import text


def initialize(root=".ariadne", model=None):
    text(model, "OpenRouter model ID")
    config = Configuration(
        providers={"openrouter": Provider("openrouter", "openrouter", "https://openrouter.ai/api/v1", "env:OPENROUTER_API_KEY")},
        prompts={"orchestrator": Prompt("orchestrator", "You are Ariadne, a project orchestrator. Help the user plan work, define tasks and acceptance criteria, and understand progress. Use tools to inspect stored facts.\n\nProject: {{project_id}}\nSummary: {{project_summary}}", ["project_id", "project_summary"])},
        profiles={"orchestrator": Profile("orchestrator", "orchestrator", description="Coordinate project work and tasks", prompt_ids=["orchestrator"], model=model, provider_id="openrouter",
                                          tools=[tool["name"] for tool in task_tools() + config_tools()], settings={"max_tool_calls": 12, "max_output_tokens": 2048, "timeout_ms": 120000})})
    ConfigurationStore(root).replace_configuration(config, expected_revision=0)
