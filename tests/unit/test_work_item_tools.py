from src.ariadne.work_items.models import (
    AgentRun,
    AgentRunStatus,
    ArtifactLink,
    ContextEntry,
    WorkItem,
    WorkItemType,
)
from src.ariadne.work_items.tools import WorkItemTools


class FakeWorkItemStore:
    def __init__(self):
        self.created = []
        self.deleted_links = []
        self.removed_comments = []
        self.started_runs = []
        self.finished_runs = []
        self.context_entries = [
            ContextEntry(
                id="1",
                work_item_id="7",
                author="Developer",
                kind="handoff",
                content="Implemented service changes.",
                created_at="2026-07-05 10:00:00",
            ),
            ContextEntry(
                id="2",
                work_item_id="7",
                author="Architect",
                kind="handoff",
                content="Selected the service design.",
                created_at="2026-07-05 10:01:00",
            )
        ]
        self.agent_runs = [
            AgentRun(
                id="99",
                work_item_id="7",
                agent_name="Developer",
                status=AgentRunStatus.SUCCESS,
                completion_payload={"summary": "Implementation complete."},
            )
        ]

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

    def get_work_item(self, work_item_id):
        return WorkItem(
            id=work_item_id,
            title="Demo work item",
            description="Build the feature.",
            status="Ready for Testing",
            type=WorkItemType.TASK,
            assignees=[],
            comments=[],
            artifacts=[
                ArtifactLink(
                    id="5",
                    title="Requirement",
                    url="docs/requirements/REQ-1.md",
                    type="requirement",
                    agent_run_id="98",
                ),
                ArtifactLink(
                    id="6",
                    title="Design",
                    url="docs/design/ARCH-1.md",
                    type="design",
                    agent_run_id="99",
                ),
                ArtifactLink(
                    id="7",
                    title="Meeting Notes",
                    url="docs/notes.md",
                    type="note",
                )
            ],
        )

    def list_context_entries(self, work_item_id):
        return self.context_entries

    def list_agent_runs(self, work_item_id):
        return self.agent_runs


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


def test_get_context_bundle_combines_work_item_context_and_agent_runs():
    store = FakeWorkItemStore()
    tools = WorkItemTools(store)

    result = tools.get_context_bundle("7", target_agent="Tester")

    assert "Work item #7: Demo work item" in result
    assert "Target agent: Tester" in result
    assert "Requirement [requirement]: docs/requirements/REQ-1.md from agent run #98" in result
    assert "Implemented service changes." in result
    assert "#99 Developer [SUCCESS]: Implementation complete." in result


def test_get_context_bundle_prioritizes_artifacts_for_target_agent():
    store = FakeWorkItemStore()
    tools = WorkItemTools(store)

    result = tools.get_context_bundle("7", target_agent="Developer", max_entries=2)

    assert "Design [design]: docs/design/ARCH-1.md from agent run #99" in result
    assert "Requirement [requirement]: docs/requirements/REQ-1.md from agent run #98" in result
    assert "Meeting Notes" not in result
    assert "... omitted 1 less relevant artifact(s)" in result


def test_get_context_bundle_prioritizes_context_for_target_agent():
    store = FakeWorkItemStore()
    tools = WorkItemTools(store)

    result = tools.get_context_bundle("7", target_agent="Developer", max_entries=1)

    assert "Selected the service design." in result
    assert "Implemented service changes." not in result
