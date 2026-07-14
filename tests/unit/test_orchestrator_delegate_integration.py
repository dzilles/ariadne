import json

from src.ariadne.agents.orchestrator_agent import OrchestratorAgent
from src.ariadne.work_items.models import WorkItemStatus


class FakeDelegatedAgent:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def chat(self, prompt):
        self.prompts.append(prompt)
        return self.response


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
        self.links.append((work_item_id, title, url, artifact_type, agent_run_id, metadata or {}))
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
        self.shared_context.append((work_item_id, author, context, agent_run_id, metadata or {}))
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


def _agent_with_ticket_tools(ticket_tools):
    agent = OrchestratorAgent.__new__(OrchestratorAgent)
    agent.ticket_tools = ticket_tools
    agent.update_work_item = ticket_tools.update_status
    agent.add_comment = ticket_tools.post_comment
    return agent


def test_delegate_to_agent_records_success_handoff(monkeypatch):
    ticket_tools = FakeTicketTools()
    orchestrator = _agent_with_ticket_tools(ticket_tools)
    completion = _completion_payload()
    fake_agent = FakeDelegatedAgent("[AGENT_RUN_COMPLETE]\n" + json.dumps(completion))

    monkeypatch.setattr(orchestrator, "_check_clean_git_status", lambda: "")
    monkeypatch.setattr(orchestrator, "_git_output", lambda args: "abc123")
    monkeypatch.setattr(
        orchestrator,
        "_collect_handoff_evidence",
        lambda: {
            "branch": "main",
            "status_short": "",
            "diff_stat": "",
            "changed_files": ["docs/requirements/REQ-999.md"],
            "latest_commit": "def456",
        },
    )
    monkeypatch.setattr(
        "src.ariadne.application.agents.AGENT_CLASSES",
        {"Requirements": lambda: fake_agent},
    )

    result = orchestrator.delegate_to_agent("Requirements", "17", "Create requirement.")

    assert result.startswith("[Requirements Response]:")
    assert ticket_tools.started_runs == [("17", "Requirements", "Create requirement.")]
    assert ticket_tools.status_updates == [("17", WorkItemStatus.READY_FOR_ANALYSIS.value)]
    assert ticket_tools.finished_runs[0][0] == "99"
    assert ticket_tools.finished_runs[0][1] == "SUCCESS"
    assert ticket_tools.finished_runs[0][2]["summary"] == completion["summary"]
    assert ticket_tools.finished_runs[0][2]["schema_version"] == 1
    assert ticket_tools.finished_runs[0][3]["starting_commit"] == "abc123"
    assert ticket_tools.finished_runs[0][4]["raw_response"].startswith("[AGENT_RUN_COMPLETE]")
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
    assert len(ticket_tools.shared_context) == 1
    assert ticket_tools.shared_context[0][3] == "99"
    assert ticket_tools.shared_context[0][4]["status"] == "SUCCESS"
    assert "bundle for 17 -> Requirements" in fake_agent.prompts[0]


def test_delegate_to_agent_records_failed_handoff(monkeypatch):
    ticket_tools = FakeTicketTools()
    orchestrator = _agent_with_ticket_tools(ticket_tools)
    completion = {
        "status": "FAILED",
        "summary": "Could not complete requirement.",
        "details": "Missing input.",
        "blockers": ["Need user clarification."],
    }
    fake_agent = FakeDelegatedAgent("[AGENT_RUN_COMPLETE]\n" + json.dumps(completion))

    monkeypatch.setattr(orchestrator, "_check_clean_git_status", lambda: "")
    monkeypatch.setattr(orchestrator, "_git_output", lambda args: "abc123")
    monkeypatch.setattr(
        orchestrator,
        "_collect_handoff_evidence",
        lambda: {
            "branch": "main",
            "status_short": "",
            "diff_stat": "",
            "changed_files": [],
            "latest_commit": "abc123",
        },
    )
    monkeypatch.setattr(
        "src.ariadne.application.agents.AGENT_CLASSES",
        {"Requirements": lambda: fake_agent},
    )

    result = orchestrator.delegate_to_agent("Requirements", "17", "Create requirement.")

    assert result.startswith("[Requirements Response]:")
    assert ticket_tools.finished_runs[0][1] == "FAILED"
    assert ("17", "Blocked") in ticket_tools.status_updates
    assert any("Need user clarification." in comment for _, comment in ticket_tools.comments)
    assert ticket_tools.links == []
    assert ticket_tools.commit_hashes == []


def test_delegate_to_agent_normalizes_malformed_handoff_as_failure(monkeypatch):
    ticket_tools = FakeTicketTools()
    orchestrator = _agent_with_ticket_tools(ticket_tools)
    response = "Success: Finished agent run 99"
    fake_agent = FakeDelegatedAgent(response)

    monkeypatch.setattr(orchestrator, "_check_clean_git_status", lambda: "")
    monkeypatch.setattr(orchestrator, "_git_output", lambda args: "abc123")
    monkeypatch.setattr(
        orchestrator,
        "_collect_handoff_evidence",
        lambda: {
            "branch": "main",
            "status_short": "",
            "diff_stat": "",
            "changed_files": [],
            "latest_commit": "abc123",
        },
    )
    monkeypatch.setattr(
        "src.ariadne.application.agents.AGENT_CLASSES",
        {"Requirements": lambda: fake_agent},
    )

    result = orchestrator.delegate_to_agent("Requirements", "17", "Create requirement.")

    assert result.startswith("[Requirements Handoff Failure]:")
    assert "required [AGENT_RUN_COMPLETE] marker" in result
    finished = ticket_tools.finished_runs[0]
    assert finished[1] == "FAILED"
    assert finished[2]["summary"] == "Requirements returned an invalid completion handoff."
    assert "required [AGENT_RUN_COMPLETE] marker" in finished[2]["details"]
    assert finished[4]["raw_response"] == response
    assert finished[4]["diagnostics"]["failure_kind"] == "invalid_completion"
    assert ("17", "Blocked") in ticket_tools.status_updates
    assert ticket_tools.shared_context[0][4]["status"] == "FAILED"


def test_delegate_to_agent_records_exception_diagnostics_and_handoff(monkeypatch):
    ticket_tools = FakeTicketTools()
    orchestrator = _agent_with_ticket_tools(ticket_tools)

    monkeypatch.setattr(orchestrator, "_check_clean_git_status", lambda: "")
    monkeypatch.setattr(orchestrator, "_git_output", lambda args: "abc123")
    monkeypatch.setattr(
        orchestrator,
        "_collect_handoff_evidence",
        lambda: {
            "branch": "main",
            "status_short": "",
            "diff_stat": "",
            "changed_files": [],
            "latest_commit": "abc123",
        },
    )
    monkeypatch.setattr(
        "src.ariadne.application.agents.AGENT_CLASSES",
        {"Requirements": FailingDelegatedAgent},
    )

    result = orchestrator.delegate_to_agent("Requirements", "17", "Create requirement.")

    assert result == "Error delegating to Requirements: provider unavailable"
    finished = ticket_tools.finished_runs[0]
    assert finished[1] == "FAILED"
    assert finished[2]["status"] == "FAILED"
    assert finished[4]["diagnostics"]["failure_kind"] == "exception"
    assert finished[4]["diagnostics"]["error_type"] == "RuntimeError"
    assert "provider unavailable" in finished[4]["diagnostics"]["traceback"]
    assert ("17", "Blocked") in ticket_tools.status_updates
    assert ticket_tools.shared_context[0][4]["status"] == "FAILED"
