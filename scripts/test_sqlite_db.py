from pathlib import Path
from tempfile import TemporaryDirectory

from src.ariadne.work_items.adapters.sqlite import SQLiteWorkItemStore
from src.ariadne.work_items.models import TicketType, TicketStatus, GateStatus
from src.ariadne.work_items.tools import WorkItemTools


def test_sqlite_system(tmp_path):
    print("🧪 Testing SQLite Ticket System...")

    store = SQLiteWorkItemStore(str(tmp_path / "ariadne.db"))
    tools = WorkItemTools(store)

    # 1. Create a ticket
    print("\n1. Creating ticket...")
    t_id = store.create_ticket(
        title="Test SQLite Ticket",
        description="This is a test ticket for the local database implementation.",
        type=TicketType.FEATURE,
        priority="high",
    )
    print(f"Created Ticket ID: {t_id}")

    # 2. Add a comment
    print("\n2. Adding comment...")
    store.post_comment(t_id, "This is a test comment.")

    # 3. Update status
    print("\n3. Updating status...")
    # Transition: Backlog -> Ready for Analysis
    store.update_status(t_id, TicketStatus.READY_FOR_ANALYSIS)

    # 4. Approve gate
    print("\n4. Approving analysis gate...")
    store.set_gate_status(t_id, "analysis", GateStatus.APPROVED)

    # 5. Add relevant commit and shared context
    print("\n5. Adding commit hash and shared context...")
    store.add_commit_hash(t_id, "abc123")
    store.update_git_metadata(
        t_id,
        target_branch="main",
        feature_branch="feature/test-sqlite-ticket",
        base_commit="base123",
        merge_request_id="MR-1",
    )
    store.append_shared_context(
        t_id,
        "Tester",
        "The requirement has enough detail for architecture.",
    )

    # 6. Verify durable tool logging at the store boundary.
    print("\n6. Verifying tool logging...")
    store.add_tool_log(
        work_item_id=t_id,
        tool_name="update_status",
        status="success",
        args={"status": TicketStatus.READY_FOR_ANALYSIS.value},
        result="status persisted",
    )

    # 7. Get ticket details
    print("\n7. Fetching ticket details...")
    item = store.get_work_item(t_id)
    assert item.created_at
    assert item.updated_at
    assert item.commit_hashes == ["abc123"]
    assert item.target_branch == "main"
    assert item.feature_branch == "feature/test-sqlite-ticket"
    assert item.base_commit == "base123"
    assert item.merge_request_id == "MR-1"
    assert "Tester" in item.shared_context
    assert "enough detail" in item.shared_context
    assert any(log.tool_name == "update_status" for log in item.tool_logs)
    ticket_details = tools.get_work_item(t_id)
    print(ticket_details)


if __name__ == "__main__":
    with TemporaryDirectory() as temp_dir:
        test_sqlite_system(Path(temp_dir))
    print("\n✅ SQLite Ticket System test PASSED!")
