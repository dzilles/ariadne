import os
import unittest
from unittest.mock import MagicMock, patch

from src.workflows.context import set_active_ticket_id, get_active_ticket_id
from src.interfaces.ticket_system import Ticket, TicketStatus, TicketType
from src.tools.file_tools import FileAgentTools
from src.tools.ticket_tools import StandardTicketTools
from src.workflows.enforcement import get_ticket_system

class MockTicketSystem:
    def __init__(self):
        self.client = MagicMock()
        self.client.get_issue_relations.return_value = []
        
    def get_ticket(self, ticket_id: str):
        if ticket_id == "1":
            return Ticket(
                id="1",
                title="Test Ticket",
                description="Test Description",
                status=TicketStatus.BACKLOG.value,
                type=TicketType.FEATURE,
                assignees=[],
                comments=[]
            )
        elif ticket_id == "2":
            return Ticket(
                id="2",
                title="Test Ticket 2",
                description="Test Description",
                status=TicketStatus.READY_FOR_ANALYSIS.value,
                type=TicketType.FEATURE,
                assignees=[],
                comments=[]
            )
        else:
            raise Exception("Ticket not found")

class TestPhase1Guard(unittest.TestCase):

    def setUp(self):
        # Reset context before each test
        set_active_ticket_id(None)

    @patch('src.workflows.enforcement.get_ticket_system')
    def test_guard_no_context(self, mock_get_ts):
        """Test that missing ticket context completely blocks mutating tools."""
        file_tools = FileAgentTools()
        result = file_tools.write_file("dummy.txt", "test")
        
        self.assertIn("⛔ BLOCK: You cannot execute mutating tools without an active ticket context", result)

    @patch('src.workflows.enforcement.get_ticket_system')
    def test_guard_wrong_status(self, mock_get_ts):
        """Test that wrong status (Backlog) blocks write_file which is not in allowed actions."""
        mock_get_ts.return_value = MockTicketSystem()
        
        set_active_ticket_id("1")  # Ticket 1 is in BACKLOG
        file_tools = FileAgentTools()
        result = file_tools.write_file("dummy.txt", "test")
        
        self.assertIn("⛔ ACTION BLOCKED", result)
        self.assertIn("You cannot perform 'write_file'", result)
        self.assertIn("Backlog", result)

    @patch('src.workflows.enforcement.get_ticket_system')
    def test_guard_success(self, mock_get_ts):
        """Test that correct status allows the action to pass through."""
        mock_get_ts.return_value = MockTicketSystem()
        
        set_active_ticket_id("2")  # Ticket 2 is in READY_FOR_ANALYSIS
        file_tools = FileAgentTools()
        
        test_file = "test_guard_success.txt"
        if os.path.exists(test_file):
            os.remove(test_file)
            
        result = file_tools.write_file(test_file, "success content")
        
        self.assertIn("Success: File written", result)
        self.assertTrue(os.path.exists(test_file))
        
        # Cleanup
        os.remove(test_file)

if __name__ == '__main__':
    unittest.main()