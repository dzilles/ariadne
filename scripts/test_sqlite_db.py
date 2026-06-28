import sys
import os
from pprint import pprint

# Add project root to path
sys.path.append(os.getcwd())

from src.ariadne.infrastructure.container import DependencyRegistry
from src.ariadne.work_items.models import TicketType, TicketStatus, GateStatus
from src.ariadne.workflows.context import set_active_ticket_id

def test_sqlite_system():
    print("🧪 Testing SQLite Ticket System...")
    
    # Force SQLite for test
    DependencyRegistry.TICKET_SYSTEM_TYPE = "sqlite"
    
    # Get tools
    tools = DependencyRegistry.get_work_item_tools()
    
    # 1. Create a ticket
    print("\n1. Creating ticket...")
    t_id = tools.system.create_ticket(
        title="Test SQLite Ticket",
        description="This is a test ticket for the local database implementation.",
        type=TicketType.FEATURE,
        priority="high"
    )
    print(f"Created Ticket ID: {t_id}")
    
    # IMPORTANT: Set active ticket ID for the JIT Guard
    set_active_ticket_id(t_id)
    
    # 2. Add a comment
    print("\n2. Adding comment...")
    res = tools.post_comment(t_id, "This is a test comment.")
    print(res)
    
    # 3. Update status
    print("\n3. Updating status...")
    # Transition: Backlog -> Ready for Analysis
    res = tools.update_status(t_id, TicketStatus.READY_FOR_ANALYSIS.value)
    print(res)
    
    # 4. Approve gate
    print("\n4. Approving analysis gate...")
    res = tools.approve_gate(t_id, "analysis")
    print(res)
    
    # 5. Get ticket details
    print("\n5. Fetching ticket details...")
    ticket_details = tools.get_work_item(t_id)
    print(ticket_details)

if __name__ == "__main__":
    # Remove existing db if exists for clean test
    if os.path.exists("ariadne_tickets.db"):
        os.remove("ariadne_tickets.db")
    
    try:
        test_sqlite_system()
        print("\n✅ SQLite Ticket System test PASSED!")
    except Exception as e:
        print(f"\n❌ Test FAILED: {e}")
        import traceback
        traceback.print_exc()
