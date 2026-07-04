from src.ariadne.work_items.models import WorkItemType
from src.ariadne.work_items.tools import WorkItemTools


class FakeWorkItemStore:
    def __init__(self):
        self.created = []
        self.deleted_links = []
        self.removed_comments = []
        self.started_runs = []
        self.finished_runs = []

    def create_work_item(self, title, description, type, priority):
        self.created.append((title, description, type, priority))
        return "42"

    def delete_artifact_link(self, work_item_id, title=None, url=None):
        self.deleted_links.append((work_item_id, title, url))

    def remove_comment(self, work_item_id, comment_id):
        self.removed_comments.append((work_item_id, comment_id))

    def start_agent_run(self, work_item_id, agent_name, task_description):
        self.started_runs.append((work_item_id, agent_name, task_description))
        return "99"

    def finish_agent_run(self, agent_run_id, status, completion_payload, evidence):
        self.finished_runs.append((agent_run_id, status, completion_payload, evidence))


def test_create_work_item_delegates_to_store():
    store = FakeWorkItemStore()
    tools = WorkItemTools(store)

    result = tools.create_work_item("Title", "Description", "Feature", "High")

    assert result == "Success: Created work item #42"
    assert store.created == [
        ("Title", "Description", WorkItemType.FEATURE, "High"),
    ]


def test_delete_link_delegates_exact_match_fields_to_store():
    store = FakeWorkItemStore()
    tools = WorkItemTools(store)

    result = tools.delete_link("7", title="Spec", url="docs/spec.md")

    assert result == "Success: Deleted matching link from work item 7"
    assert store.deleted_links == [("7", "Spec", "docs/spec.md")]


def test_remove_comment_delegates_to_store():
    store = FakeWorkItemStore()
    tools = WorkItemTools(store)

    result = tools.remove_comment("7", "12")

    assert result == "Success: Removed comment 12 from work item 7"
    assert store.removed_comments == [("7", "12")]


def test_start_agent_run_delegates_to_store():
    store = FakeWorkItemStore()
    tools = WorkItemTools(store)

    result = tools.start_agent_run("7", "Developer", "Build it")

    assert result == "99"
    assert store.started_runs == [("7", "Developer", "Build it")]


def test_finish_agent_run_delegates_to_store():
    store = FakeWorkItemStore()
    tools = WorkItemTools(store)
    completion = {"status": "SUCCESS", "summary": "Done"}
    evidence = {"branch": "main"}

    result = tools.finish_agent_run("99", "SUCCESS", completion, evidence)

    assert result == "Success: Finished agent run 99"
    assert store.finished_runs[0][0] == "99"
    assert store.finished_runs[0][1].value == "SUCCESS"
    assert store.finished_runs[0][2] == completion
    assert store.finished_runs[0][3] == evidence
