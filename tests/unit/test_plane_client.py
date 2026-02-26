import unittest
from unittest.mock import patch, MagicMock
import os
from src.tools.plane_client import PlaneInteraction

class TestPlaneInteraction(unittest.TestCase):

    def setUp(self):
        # Set up environment variables for testing
        os.environ["PLANE_API_URL"] = "http://test-api/api/v1"
        os.environ["PLANE_API_KEY"] = "test-key"
        os.environ["PLANE_WS_SLUG"] = "test-workspace"
        os.environ["PLANE_PROJECT_ID"] = "test-project-uuid"
        
        self.client = PlaneInteraction()

    @patch("requests.get")
    def test_get_issue_by_number_success(self, mock_get):
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [{"id": "issue-uuid", "sequence_id": 12, "name": "Test Issue"}]}
        mock_get.return_value = mock_response

        issue = self.client.get_issue_by_number(12)
        
        self.assertIsNotNone(issue)
        self.assertEqual(issue["sequence_id"], 12)
        self.assertEqual(issue["name"], "Test Issue")
        mock_get.assert_called_once()

    @patch("requests.post")
    def test_create_issue(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "new-uuid", "name": "New Issue"}
        mock_post.return_value = mock_response

        issue = self.client.create_issue("New Issue", "Description", priority="High")
        
        self.assertIn("Success: Created Ticket", issue)
        # Verify priority was lowercased
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["priority"], "high")

    @patch("requests.get")
    @patch("requests.patch")
    def test_update_issue_status(self, mock_patch, mock_get):
        # 1. Mock get_issue_by_number
        # 2. Mock _get_state_id (via mock_get)
        # 3. Mock patch request
        
        mock_get_response = MagicMock()
        mock_get_response.status_code = 200
        
        def mock_get_side_effect(url, **kwargs):
            if "/issues/" in url:
                return MagicMock(status_code=200, json=lambda: {"results": [{"id": "issue-uuid", "sequence_id": 12}]})
            if "/states/" in url:
                return MagicMock(status_code=200, json=lambda: [{"id": "state-uuid", "name": "In Progress"}])
            return MagicMock(status_code=404)

        mock_get.side_effect = mock_get_side_effect
        
        mock_patch_response = MagicMock()
        mock_patch_response.status_code = 200
        mock_patch_response.json.return_value = {"id": "issue-uuid", "state": "state-uuid"}
        mock_patch.return_value = mock_patch_response

        updated_issue = self.client.update_issue_status(12, "In Progress")
        
        self.assertEqual(updated_issue, "Success: Updated Issue 12")
        mock_patch.assert_called_once()

    @patch("requests.get")
    def test_list_issues(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"sequence_id": 1, "name": "Issue 1", "state_detail": {"name": "Todo"}},
                {"sequence_id": 2, "name": "Issue 2", "state_detail": {"name": "Done"}}
            ]
        }
        mock_get.return_value = mock_response

        issues = self.client.list_issues()
        
        self.assertEqual(len(issues), 2)
        self.assertEqual(issues[0]["number"], 1)
        self.assertEqual(issues[0]["status"], "Todo")

if __name__ == "__main__":
    unittest.main()
