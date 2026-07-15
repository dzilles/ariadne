from src.ariadne.agents.orchestrator_agent import OrchestratorAgent
from src.ariadne.application.delegation import DelegationService
from src.ariadne.runtime import run_manager
from src.ariadne.work_items.models import AgentRunStatus, WorkItemStatus


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
        self.started_runs = []
        self.finished_runs = []
        self.status_updates = []
        self.comments = []
        self.links = []
        self.commit_hashes = []
        self.shared_context = []

    def get_context_bundle(self, work_item_id, target_agent=""):
        return f"bundle for {work_item_id} -> {target_agent}"

    def start_agent_run(self, work_item_id, agent_name, task_description):
        self.started_runs.append((work_item_id, agent_name, task_description))
        return "99"

    def finish_agent_run(
        self,
        agent_run_id,
        status,
        completion_payload,
        evidence,
        exit_status="",
        raw_response="",
        diagnostics=None,
    ):
        self.finished_runs.append(
            (
                agent_run_id,
                status,
                completion_payload,
                evidence,
                {
                    "exit_status": exit_status,
                    "raw_response": raw_response,
                    "diagnostics": diagnostics or {},
                },
            )
        )
        return "ok"

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
    assert ticket_tools.status_updates == [
        ("17", WorkItemStatus.READY_FOR_ANALYSIS.value)
    ]
    assert ticket_tools.finished_runs[0][0] == "99"
    assert ticket_tools.finished_runs[0][1] == "SUCCESS"
    assert ticket_tools.finished_runs[0][2]["schema_version"] == 1
    assert ticket_tools.finished_runs[0][3]["starting_commit"] == "abc123"
    assert ticket_tools.finished_runs[0][4]["raw_response"].startswith(
        "[AGENT_RUN_COMPLETE]"
    )
    assert ticket_tools.commit_hashes == [("17", "def456")]
    assert ticket_tools.links == [
        (
            "17",
            "Requirement",
            "docs/requirements/REQ-999.md",
            "requirement",
            "99",
            {"stable_id": "REQ-999"},
        )
    ]
    assert ticket_tools.shared_context[0][3] == "99"
    assert ticket_tools.shared_context[0][4]["status"] == "SUCCESS"
    assert "bundle for 17 -> Requirements" in agents[0].prompts[0]
    assert "`return_to_orchestrator` exactly once" in agents[0].prompts[0]


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
    assert ticket_tools.finished_runs[0][1] == "FAILED"
    assert ("17", "Blocked") in ticket_tools.status_updates
    assert any(
        "Need user clarification." in comment for _, comment in ticket_tools.comments
    )
    assert ticket_tools.links == []
    assert ticket_tools.commit_hashes == []


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
    finished = ticket_tools.finished_runs[0]
    assert (
        finished[2]["summary"] == "Requirements returned an invalid completion handoff."
    )
    assert finished[4]["raw_response"] == "Finished without a terminal completion."
    assert finished[4]["diagnostics"]["failure_kind"] == "invalid_completion"
    assert ("17", "Blocked") in ticket_tools.status_updates


def test_delegate_rejects_duplicate_terminal_completion(monkeypatch):
    ticket_tools = FakeTicketTools()
    service = _service(monkeypatch, ticket_tools, DuplicateCompletionAgent)

    result = service.delegate("Requirements", "17", "Create requirement.")

    assert result.run_status == AgentRunStatus.FAILED
    assert "more than once" in result.completion.details
    assert ticket_tools.finished_runs[0][4]["diagnostics"]["failure_kind"] == (
        "invalid_completion"
    )


def test_delegate_records_exception_diagnostics_and_handoff(monkeypatch):
    ticket_tools = FakeTicketTools()
    service = _service(monkeypatch, ticket_tools, FailingDelegatedAgent)

    result = service.delegate("Requirements", "17", "Create requirement.")

    assert result.to_orchestrator_message() == (
        "Error delegating to Requirements: provider unavailable"
    )
    finished = ticket_tools.finished_runs[0]
    assert finished[1] == "FAILED"
    assert finished[4]["diagnostics"]["failure_kind"] == "exception"
    assert finished[4]["diagnostics"]["error_type"] == "RuntimeError"
    assert "provider unavailable" in finished[4]["diagnostics"]["traceback"]
    assert ("17", "Blocked") in ticket_tools.status_updates


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
    assert ticket_tools.finished_runs[0][1] == "CANCELLED"
    assert ticket_tools.finished_runs[0][4]["diagnostics"]["failure_kind"] == (
        "cancelled"
    )
    assert ("17", "Blocked") not in ticket_tools.status_updates
    assert ticket_tools.shared_context[0][4]["status"] == "CANCELLED"


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
