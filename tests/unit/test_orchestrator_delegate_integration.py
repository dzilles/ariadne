from src.ariadne.agents.orchestrator_agent import OrchestratorAgent
from src.ariadne.application.delegation import DelegationService
from src.ariadne.runtime import run_manager
from src.ariadne.work_items.adapters.sqlite import SQLiteWorkItemStore
from src.ariadne.work_items.models import (
    AgentRunStatus,
    WorkItem,
    WorkItemStatus,
    WorkItemType,
)
from src.ariadne.work_items.tools import WorkItemTools


class CompletingDelegatedAgent:
    def __init__(self, agent_run_tools, completion):
        self.agent_run_tools = agent_run_tools
        self.completion = completion
        self.prompts = []

    def chat(self, prompt):
        self.prompts.append(prompt)
        return self.agent_run_tools.return_to_orchestrator(**self.completion)


class MalformedDelegatedAgent:
    def chat(self, prompt):
        return "Finished without a terminal completion."


class DuplicateCompletionAgent:
    def __init__(self, agent_run_tools):
        self.agent_run_tools = agent_run_tools

    def chat(self, prompt):
        self.agent_run_tools.return_to_orchestrator("SUCCESS", "First completion.")
        return self.agent_run_tools.finish_agent_run("SUCCESS", "Second completion.")


class FailingDelegatedAgent:
    def chat(self, prompt):
        raise RuntimeError("provider unavailable")


class FakeTicketTools:
    def __init__(self):
        self.system = self
        self.started_runs = []
        self.finalized_runs = []
        self.status_updates = []
        self.comments = []
        self.links = []
        self.commit_hashes = []
        self.shared_context = []

    def get_work_item(self, work_item_id):
        return WorkItem(
            id=work_item_id,
            title="Smoke requirement",
            description="Create it.",
            status=WorkItemStatus.READY_FOR_ANALYSIS.value,
            type=WorkItemType.TASK,
            assignees=[],
            comments=[],
        )

    def get_running_agent_run(self, work_item_id):
        return None

    def get_blockers(self, work_item_id):
        return []

    def get_context_bundle(self, work_item_id, target_agent=""):
        return f"bundle for {work_item_id} -> {target_agent}"

    def start_agent_run(self, work_item_id, agent_name, task_description):
        self.started_runs.append((work_item_id, agent_name, task_description))
        return "99"

    def finalize_agent_run(self, agent_run_id, finalization):
        self.finalized_runs.append((agent_run_id, finalization))
        return f"Success: Finalized agent run {agent_run_id}"

    def update_status(self, work_item_id, status):
        self.status_updates.append((work_item_id, status))
        return "ok"

    def post_comment(self, work_item_id, comment):
        self.comments.append((work_item_id, comment))
        return "ok"

    def add_link(
        self,
        work_item_id,
        title,
        url,
        comment=None,
        artifact_type="link",
        agent_run_id=None,
        metadata=None,
    ):
        self.links.append(
            (work_item_id, title, url, artifact_type, agent_run_id, metadata or {})
        )
        return "ok"

    def add_commit_hash(self, work_item_id, commit_hash):
        self.commit_hashes.append((work_item_id, commit_hash))
        return "ok"

    def append_shared_context(
        self,
        work_item_id,
        author,
        context,
        agent_run_id=None,
        metadata=None,
    ):
        self.shared_context.append(
            (work_item_id, author, context, agent_run_id, metadata or {})
        )
        return "ok"


def _completion_payload(status="SUCCESS"):
    return {
        "status": status,
        "summary": "Created smoke requirement.",
        "details": "Wrote the requirement file.",
        "decisions": ["Use structured handoff."],
        "blockers": [],
        "artifacts": [
            {
                "title": "Requirement",
                "url": "docs/requirements/REQ-999.md",
                "type": "requirement",
                "stable_id": "REQ-999",
            }
        ],
    }


def _service(monkeypatch, ticket_tools, agent_factory):
    service = DelegationService(
        ticket_tools,
        agent_factories={"Requirements": agent_factory},
        project_path=".",
    )
    monkeypatch.setattr(service, "_check_clean_git_status", lambda: "")
    monkeypatch.setattr(service, "_git_output", lambda args: "abc123")
    monkeypatch.setattr(
        service,
        "_collect_handoff_evidence",
        lambda: {
            "branch": "main",
            "status_short": "",
            "diff_stat": "",
            "changed_files": ["docs/requirements/REQ-999.md"],
            "latest_commit": "def456",
        },
    )
    return service


def test_delegate_records_typed_success_handoff(monkeypatch):
    ticket_tools = FakeTicketTools()
    completion = _completion_payload()
    agents = []

    def agent_factory(agent_run_tools):
        agent = CompletingDelegatedAgent(agent_run_tools, completion)
        agents.append(agent)
        return agent

    service = _service(monkeypatch, ticket_tools, agent_factory)

    result = service.delegate("Requirements", "17", "Create requirement.")

    assert result.run_status == AgentRunStatus.SUCCESS
    assert result.completion.summary == completion["summary"]
    assert "[AGENT_RUN_COMPLETE]" not in result.to_orchestrator_message()
    assert ticket_tools.started_runs == [("17", "Requirements", "Create requirement.")]
    assert ticket_tools.status_updates == []
    assert ticket_tools.finalized_runs[0][0] == "99"
    finalization = ticket_tools.finalized_runs[0][1]
    assert finalization.run_status == AgentRunStatus.SUCCESS
    assert finalization.completion.schema_version == 1
    assert finalization.evidence["starting_commit"] == "abc123"
    assert finalization.raw_response.startswith("[AGENT_RUN_COMPLETE]")
    assert finalization.next_status == WorkItemStatus.READY_FOR_REVIEW.value
    assert finalization.commit_hashes == ["def456"]
    assert finalization.completion.artifacts[0].stable_id == "REQ-999"
    assert finalization.handoff_metadata["status"] == "SUCCESS"
    assert "bundle for 17 -> Requirements" in agents[0].prompts[0]
    assert "`return_to_orchestrator` exactly once" in agents[0].prompts[0]


def test_delegate_success_finalizes_into_real_sqlite_store(monkeypatch, tmp_path):
    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    work_item_id = store.create_work_item(
        "Smoke requirement",
        "Create it.",
        WorkItemType.TASK,
        "Medium",
    )
    store.update_status(work_item_id, WorkItemStatus.READY_FOR_ANALYSIS)
    ticket_tools = WorkItemTools(store)

    def agent_factory(agent_run_tools):
        return CompletingDelegatedAgent(agent_run_tools, _completion_payload())

    service = DelegationService(
        ticket_tools,
        agent_factories={"Requirements": agent_factory},
        project_path=".",
    )
    monkeypatch.setattr(service, "_check_clean_git_status", lambda: "")
    monkeypatch.setattr(service, "_git_output", lambda args: "abc123")
    monkeypatch.setattr(
        service,
        "_collect_handoff_evidence",
        lambda: {
            "branch": "main",
            "status_short": "",
            "diff_stat": "",
            "changed_files": ["docs/requirements/REQ-999.md"],
            "latest_commit": "def456",
        },
    )

    result = service.delegate(
        "Requirements",
        work_item_id,
        "Create requirement.",
    )

    work_item = store.get_work_item(work_item_id)
    run = store.list_agent_runs(work_item_id)[0]
    assert result.run_status == AgentRunStatus.SUCCESS
    assert run.status == AgentRunStatus.SUCCESS
    assert work_item.status == WorkItemStatus.READY_FOR_REVIEW.value
    assert work_item.commit_hashes == ["def456"]
    assert work_item.artifacts[0].url == "docs/requirements/REQ-999.md"
    assert store.list_context_entries(work_item_id)[0].agent_run_id == run.id


def test_delegate_records_explicit_failed_handoff(monkeypatch):
    ticket_tools = FakeTicketTools()
    completion = {
        "status": "FAILED",
        "summary": "Could not complete requirement.",
        "details": "Missing input.",
        "blockers": ["Need user clarification."],
    }
    service = _service(
        monkeypatch,
        ticket_tools,
        lambda agent_run_tools: CompletingDelegatedAgent(agent_run_tools, completion),
    )

    result = service.delegate("Requirements", "17", "Create requirement.")

    assert result.run_status == AgentRunStatus.FAILED
    finalization = ticket_tools.finalized_runs[0][1]
    assert finalization.run_status == AgentRunStatus.FAILED
    assert finalization.exit_status == "Blocked"
    assert finalization.resumable_status == WorkItemStatus.READY_FOR_ANALYSIS.value
    assert "Need user clarification." in finalization.comment
    assert finalization.commit_hashes == ["def456"]


def test_delegate_normalizes_missing_terminal_completion_as_failure(monkeypatch):
    ticket_tools = FakeTicketTools()
    service = _service(monkeypatch, ticket_tools, MalformedDelegatedAgent)

    result = service.delegate("Requirements", "17", "Create requirement.")

    assert result.run_status == AgentRunStatus.FAILED
    assert result.to_orchestrator_message().startswith(
        "[Requirements Handoff Failure]:"
    )
    assert (
        "did not call return_to_orchestrator exactly once" in result.completion.details
    )
    finalization = ticket_tools.finalized_runs[0][1]
    assert finalization.completion.summary == (
        "Requirements returned an invalid completion handoff."
    )
    assert finalization.raw_response == "Finished without a terminal completion."
    assert finalization.diagnostics["failure_kind"] == "invalid_completion"


def test_delegate_rejects_duplicate_terminal_completion(monkeypatch):
    ticket_tools = FakeTicketTools()
    service = _service(monkeypatch, ticket_tools, DuplicateCompletionAgent)

    result = service.delegate("Requirements", "17", "Create requirement.")

    assert result.run_status == AgentRunStatus.FAILED
    assert "more than once" in result.completion.details
    assert ticket_tools.finalized_runs[0][1].diagnostics["failure_kind"] == (
        "invalid_completion"
    )


def test_delegate_records_exception_diagnostics_and_handoff(monkeypatch):
    ticket_tools = FakeTicketTools()
    service = _service(monkeypatch, ticket_tools, FailingDelegatedAgent)

    result = service.delegate("Requirements", "17", "Create requirement.")

    assert result.to_orchestrator_message() == (
        "Error delegating to Requirements: provider unavailable"
    )
    finalization = ticket_tools.finalized_runs[0][1]
    assert finalization.run_status == AgentRunStatus.FAILED
    assert finalization.diagnostics["failure_kind"] == "exception"
    assert finalization.diagnostics["error_type"] == "RuntimeError"
    assert "provider unavailable" in finalization.diagnostics["traceback"]


def test_delegate_finalizes_cancelled_run_without_blocking_ticket(monkeypatch):
    ticket_tools = FakeTicketTools()
    service = _service(
        monkeypatch,
        ticket_tools,
        lambda agent_run_tools: CompletingDelegatedAgent(
            agent_run_tools,
            _completion_payload(),
        ),
    )
    monkeypatch.setattr(run_manager, "is_cancel_requested", lambda: True)

    result = service.delegate("Requirements", "17", "Create requirement.")

    assert result.run_status == AgentRunStatus.CANCELLED
    finalization = ticket_tools.finalized_runs[0][1]
    assert finalization.run_status == AgentRunStatus.CANCELLED
    assert finalization.diagnostics["failure_kind"] == ("cancelled")
    assert finalization.exit_status == WorkItemStatus.READY_FOR_ANALYSIS.value
    assert finalization.handoff_metadata["status"] == "CANCELLED"


def test_orchestrator_presents_service_result_without_parsing_response():
    class FakeResult:
        def to_orchestrator_message(self):
            return "typed completion"

    class FakeService:
        def delegate(self, agent_name, work_item_id, task_description):
            assert (agent_name, work_item_id, task_description) == (
                "Requirements",
                "17",
                "Create requirement.",
            )
            return FakeResult()

    orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
    orchestrator.delegation_service = FakeService()

    assert (
        orchestrator.delegate_to_agent("Requirements", "17", "Create requirement.")
        == "typed completion"
    )
