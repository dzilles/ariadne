import copy

from ariadne._util import to_data
from ariadne.errors import Error
from ariadne.task import tools as task_tools, DemoEmbedder
from ariadne.configuration import tools as config_tools
from ariadne.llm import ToolDefinition


class TaskTools:
    def __init__(self, store, configuration, project_id, profile_id="orchestrator"):
        self.store, self.configuration, self.project_id, self.profile_id = store, configuration, project_id, profile_id

    @staticmethod
    def definitions(configuration, profile_id):
        profile = configuration.profiles.get(profile_id)
        if profile is None:
            raise Error("NOT_FOUND", "Orchestrator profile does not exist")
        catalog = {item["name"]: item for item in task_tools.tool_definitions() + config_tools.tool_definitions()}
        selected = []
        for name in profile.tools:
            if name not in catalog:
                raise Error.invalid(f"Orchestrator tool {name} is unavailable")
            tool = copy.deepcopy(catalog[name])
            tool["input_schema"].get("properties", {}).pop("project_id", None)
            if "required" in tool["input_schema"]:
                tool["input_schema"]["required"] = [key for key in tool["input_schema"]["required"] if key != "project_id"]
            selected.append(ToolDefinition.from_dict(tool))
        return selected

    def call(self, name, arguments):
        definition = next((item for item in self.definitions(self.configuration, self.profile_id) if item.name == name), None)
        if definition is None:
            raise Error("FORBIDDEN", "Tool is not enabled for this profile")
        task_tools.validate_arguments(arguments, definition.input_schema)
        arguments = copy.deepcopy(arguments)
        if any(tool["name"] == name for tool in task_tools.tool_definitions()):
            field = "id" if name in ("get_task", "update_task", "get_history") else "task_id" if name in ("add_note", "annotate_reference") else None
            if field and self.store.orchestrator().get_task(arguments[field]).project_id != self.project_id:
                raise Error("FORBIDDEN", "Task belongs to another project")
            if name in ("create_task", "search_tasks"):
                arguments["project_id"] = self.project_id
            if name == "search_tasks" and arguments.get("mode") == "semantic":
                self.store.index_pending(DemoEmbedder(), 200)
            return to_data(task_tools.call(self.store, name, arguments))
        return to_data(config_tools.call(self.configuration, name, arguments))
