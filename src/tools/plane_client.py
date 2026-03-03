import os
import time
import logging
import requests
import threading
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

class PlaneAPIError(Exception):
    """Custom exception for Plane API errors."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Plane API Error {status_code}: {message}")

class PlaneInteraction:
    """
    Interface between AI agents and the self-hosted Plane API.
    """

    def __init__(self, api_key: str = None):
        """
        Initialize the PlaneInteraction class by loading configuration.
        """
        from src.configuration.config import settings
        
        self.api_url = settings.plane_api_url
        self.api_key = api_key or settings.plane_api_token or os.getenv("PLANE_API_KEY")
        self.ws_slug = settings.plane_ws_slug or os.getenv("PLANE_WS_SLUG")
        self.project_id = settings.plane_project_id or os.getenv("PLANE_PROJECT_ID")
        
        # Caches
        self._state_cache: Dict[str, str] = {}
        self._member_cache: Dict[str, str] = {}
        self._label_cache: Dict[str, str] = {}
        
        # Lock for serialization
        self._lock = threading.Lock()

        if not self.api_key:
            logger.error("Plane API Key not found. Please ensure the secret-key CSV is in .config/ or .plane/")
            raise ValueError("Missing Plane API Key.")

        if not self.ws_slug or not self.project_id:
            logger.info("PLANE_WS_SLUG or PLANE_PROJECT_ID missing. Attempting auto-discovery...")
            self._discover_ids()

        self.base_url = f"{self.api_url}/workspaces/{self.ws_slug}/projects/{self.project_id}"

    def _discover_ids(self):
        """Attempts to discover the workspace slug and project ID using the API key."""
        headers = self._get_headers()
        if not self.ws_slug:
            try:
                response = requests.get(f"{self.api_url}/workspaces/", headers=headers)
                data = self._handle_response(response)
                results = data.get("results", []) if isinstance(data, dict) else data
                if results:
                    self.ws_slug = results[0].get("slug")
                    logger.info(f"Discovered Workspace Slug: {self.ws_slug}")
            except Exception as e:
                logger.error(f"Failed to discover workspace: {e}")

        if self.ws_slug and not self.project_id:
            try:
                response = requests.get(f"{self.api_url}/workspaces/{self.ws_slug}/projects/", headers=headers)
                data = self._handle_response(response)
                results = data.get("results", []) if isinstance(data, dict) else data
                if results:
                    self.project_id = results[0].get("id")
                    logger.info(f"Discovered Project ID: {self.project_id}")
            except Exception as e:
                logger.error(f"Failed to discover project: {e}")

    def _get_headers(self) -> Dict[str, str]:
        return {"x-api-key": self.api_key, "Content-Type": "application/json"}

    def _handle_response(self, response: requests.Response, ignore_errors: List[int] = None) -> Any:
        if 200 <= response.status_code < 300:
            try:
                return response.json()
            except ValueError:
                return {}
        else:
            # We keep the logging active as per user request to see all errors
            logger.error(f"API request failed: {response.status_code} - {response.text}")
            raise PlaneAPIError(response.status_code, response.text)

    def _get_state_id(self, status_name: str) -> Optional[str]:
        if status_name in self._state_cache:
            return self._state_cache[status_name]
        self._refresh_state_cache()
        return self._state_cache.get(status_name)

    def _refresh_state_cache(self):
        """Fetches all states and populates the cache and ID-to-detail map."""
        url = f"{self.base_url}/states/"
        try:
            response = requests.get(url, headers=self._get_headers())
            data = self._handle_response(response)
            states = data.get("results", []) if isinstance(data, dict) else data
            self._state_cache = {}
            self._state_id_map = {}
            for state in states:
                self._state_cache[state.get("name")] = state.get("id")
                self._state_id_map[state.get("id")] = state
        except Exception:
            pass

    def _get_member_id(self, email_or_name: str) -> Optional[str]:
        if email_or_name in self._member_cache:
            return self._member_cache[email_or_name]
        url = f"{self.base_url}/members/"
        try:
            response = requests.get(url, headers=self._get_headers())
            data = self._handle_response(response)
            members = data.get("results", []) if isinstance(data, dict) else data
            for member in members:
                m_info = member.get("member", {})
                uid, email, name = m_info.get("id"), m_info.get("email"), m_info.get("display_name")
                if uid:
                    if email: self._member_cache[email] = uid
                    if name: self._member_cache[name] = uid
            return self._member_cache.get(email_or_name)
        except Exception:
            return None

    def _get_label_id(self, name: str) -> Optional[str]:
        if name in self._label_cache:
            return self._label_cache[name]
        url = f"{self.base_url}/labels/"
        try:
            response = requests.get(url, headers=self._get_headers())
            data = self._handle_response(response)
            labels = data.get("results", []) if isinstance(data, dict) else data
            for label in labels:
                self._label_cache[label.get("name")] = label.get("id")
            return self._label_cache.get(name)
        except Exception:
            return None

    def _resolve_id(self, id_or_number: Any) -> str:
        """
        Resolves a Sequence Number (int or str) or UUID to a UUID.
        """
        input_str = str(id_or_number)
        
        # Check if it's already a UUID (8-4-4-4-12 pattern)
        import re
        if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', input_str.lower()):
            return input_str

        # Assume it's a sequence number
        try:
            num = int(input_str)
            issue = self.get_issue_by_number(num)
            if issue and 'id' in issue:
                return issue['id']
        except (ValueError, TypeError):
            pass
            
        return input_str 

    def get_issue_by_number(self, sequence_id: int) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/issues/"
        params = {"sequence_id": sequence_id}
        response = requests.get(url, headers=self._get_headers(), params=params)
        data = self._handle_response(response)
        results = data.get("results", []) if isinstance(data, dict) else data
        for issue in results:
            if issue.get("sequence_id") == sequence_id:
                # Return the full issue details by fetching it specifically by ID
                return self.get_issue_by_id(issue.get("id"))
        return None

    def get_issue_by_id(self, issue_id: str) -> Optional[Dict[str, Any]]:
        """Fetch an issue directly by its UUID."""
        url = f"{self.base_url}/issues/{issue_id}/"
        try:
            response = requests.get(url, headers=self._get_headers())
            if response.status_code == 404:
                return None
            data = self._handle_response(response)
            
            # Enrich with state_detail if missing
            if data and "state" in data and not data.get("state_detail"):
                if not hasattr(self, "_state_id_map") or data["state"] not in self._state_id_map:
                    self._refresh_state_cache()
                
                if hasattr(self, "_state_id_map") and data["state"] in self._state_id_map:
                    data["state_detail"] = self._state_id_map[data["state"]]
            
            return data
        except Exception:
            return None

    def create_issue(self, title: str, description: str, priority: str = "medium", type: str = "Issue") -> str:
        url = f"{self.base_url}/issues/"
        payload = {"name": title, "description_html": f"<p>{description}</p>", "priority": priority.lower()}
        with self._lock:
            logger.info(f"Creating issue: {title}")
            response = requests.post(url, headers=self._get_headers(), json=payload)
            data = self._handle_response(response)
            time.sleep(2)
            return f"Success: Created Ticket {data.get('sequence_id')} - '{data.get('name')}' (ID: {data.get('id')})"

    def create_sub_issue(self, parent_issue_number: int, title: str, description: str) -> str:
        with self._lock:
            parent_id = self._resolve_id(parent_issue_number)
            url = f"{self.base_url}/issues/"
            payload = {"name": title, "description_html": f"<p>{description}</p>", "parent": parent_id}
            logger.info(f"Creating sub-issue for parent {parent_issue_number}: {title}")
            response = requests.post(url, headers=self._get_headers(), json=payload)
            data = self._handle_response(response)
            time.sleep(2)
            return f"Success: Created Sub-Ticket {data.get('sequence_id')} - '{data.get('name')}' under Parent {parent_issue_number}"

    def delete_issue(self, issue_number: int) -> str:
        """
        Deletes an issue by its sequence ID or UUID.
        """
        issue_id = self._resolve_id(issue_number)
        url = f"{self.base_url}/issues/{issue_id}/"

        with self._lock:
            logger.info(f"Deleting issue: {issue_number}")
            response = requests.delete(url, headers=self._get_headers())
            if 200 <= response.status_code < 300:
                return f"Success: Deleted Issue {issue_number}"
            else:
                logger.error(f"API request failed: {response.status_code} - {response.text}")
                raise PlaneAPIError(response.status_code, response.text)

    def update_issue(self, issue_number: int, title: str = None, description: str = None, priority: str = None,
                     state: str = None, assignees: List[str] = None, start_date: str = None, due_date: str = None,
                     parent_issue_number: int = None, labels: List[str] = None) -> str:
        issue_id = self._resolve_id(issue_number)
        url = f"{self.base_url}/issues/{issue_id}/"
        payload = {}
        if title: payload["name"] = title
        if description: payload["description_html"] = f"<p>{description}</p>"
        if priority: payload["priority"] = priority.lower()
        if start_date: payload["start_date"] = start_date
        if due_date: payload["target_date"] = due_date
        if state:
            s_id = self._get_state_id(state)
            if s_id: payload["state"] = s_id
            else: raise PlaneAPIError(404, f"State '{state}' not found")
        if assignees is not None:
            m_ids = [self._get_member_id(a) for a in assignees]
            if None in m_ids: raise PlaneAPIError(404, "One or more members not found")
            payload["assignees"] = m_ids
        if labels is not None:
            l_ids = [self._get_label_id(l) for l in labels]
            if None in l_ids: raise PlaneAPIError(404, "One or more labels not found")
            payload["labels"] = l_ids
        if parent_issue_number is not None:
            payload["parent"] = self._resolve_id(parent_issue_number)
        if not payload: raise ValueError("No fields provided to update")
        response = requests.patch(url, headers=self._get_headers(), json=payload)
        self._handle_response(response)
        return f"Success: Updated Issue {issue_number}"

    def update_issue_status(self, issue_number: int, status_name: str) -> str:
        return self.update_issue(issue_number, state=status_name)

    def add_comment(self, issue_number: int, comment_text: str) -> str:
        issue_id = self._resolve_id(issue_number)
        url = f"{self.base_url}/issues/{issue_id}/comments/"
        payload = {"comment_html": f"<p>{comment_text}</p>"}
        response = requests.post(url, headers=self._get_headers(), json=payload)
        self._handle_response(response)
        return f"Success: Added comment to Issue {issue_number}"

    def get_comments(self, issue_number: int) -> Any:
        issue_id = self._resolve_id(issue_number)
        url = f"{self.base_url}/issues/{issue_id}/comments/"
        response = requests.get(url, headers=self._get_headers())
        data = self._handle_response(response, ignore_errors=[404])
        return data.get("results", []) if isinstance(data, dict) else data

    def get_comment_url(self, issue_number: int, comment_id: str) -> str:
        """Constructs a direct permalink to a comment."""
        issue_id = self._resolve_id(issue_number)
        web_base = os.getenv("WEB_URL", "http://localhost:8090")
        return f"{web_base}/{self.ws_slug}/projects/{self.project_id}/issues/{issue_id}#comment-{comment_id}"

    def add_issue_link(self, issue_number: int, url: str, title: str = None) -> str:
        issue_id = self._resolve_id(issue_number)
        endpoint = f"{self.base_url}/issues/{issue_id}/links/"
        payload = {"url": url, "title": title or url}
        response = requests.post(endpoint, headers=self._get_headers(), json=payload)
        self._handle_response(response)
        return f"Success: Added link {url} to Issue {issue_number}"

    def add_issue_relation(self, issue_number: int, related_issue_number: int, relation_type: str = "relates_to") -> str:
        source_id = self._resolve_id(issue_number)
        related_id = self._resolve_id(related_issue_number)

        url = f"{self.base_url}/issues/{source_id}/relations/"
        payload = {
            "related_issue": related_id,
            "relation_type": relation_type
        }

        response = requests.post(url, headers=self._get_headers(), json=payload)
        self._handle_response(response)
        return f"Success: Added relation '{relation_type}' between {issue_number} and {related_issue_number}"

    def upload_attachment(self, issue_number: int, file_path: str) -> str:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File {file_path} not found")
        issue_id = self._resolve_id(issue_number)
        endpoint = f"{self.base_url}/issues/{issue_id}/attachments/"
        headers = {"x-api-key": self.api_key}
        with open(file_path, 'rb') as f:
            files = {'asset': (os.path.basename(file_path), f)}
            response = requests.post(endpoint, headers=headers, files=files)
        if 200 <= response.status_code < 300:
            return f"Success: Attached {os.path.basename(file_path)} to Issue {issue_number}"
        else:
            raise PlaneAPIError(response.status_code, response.text)

    def get_issue_links(self, issue_id: str) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/issues/{issue_id}/links/"
        try:
            response = requests.get(url, headers=self._get_headers())
            data = self._handle_response(response, ignore_errors=[404])
            return data.get("results", []) if isinstance(data, dict) else data
        except Exception: return []

    def get_issue_relations(self, issue_id: str) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/issues/{issue_id}/relations/"
        try:
            response = requests.get(url, headers=self._get_headers())
            data = self._handle_response(response, ignore_errors=[404])
            return data.get("results", []) if isinstance(data, dict) else data
        except Exception: return []

    def list_issues(self, state_group: str = None, search_query: str = None, priority: str = None, 
                    assignees: List[str] = None, labels: List[str] = None, state: str = None) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/issues/"
        params = {}
        if state_group: params["state_group"] = state_group
        if search_query: params["search"] = search_query
        if priority: params["priority"] = priority.lower()
        if state:
            s_id = self._get_state_id(state)
            if s_id: params["state"] = s_id
        if assignees:
            m_ids = [self._get_member_id(a) for a in assignees]
            params["assignees"] = ",".join([mid for mid in m_ids if mid])
        if labels:
            l_ids = [self._get_label_id(l) for l in labels]
            params["labels"] = ",".join([lid for lid in l_ids if lid])
        response = requests.get(url, headers=self._get_headers(), params=params)
        data = self._handle_response(response)
        results = data.get("results", []) if isinstance(data, dict) else data
        simplified_issues = []
        for issue in results:
            assignees_list = []
            for m in issue.get("assignees", []):
                if isinstance(m, dict):
                    assignees_list.append(m.get("member", {}).get("display_name") or "Unknown")
                elif isinstance(m, str): assignees_list.append(m)
            simplified_issues.append({
                "number": issue.get("sequence_id"), "title": issue.get("name"),
                "status": issue.get("state_detail", {}).get("name") or issue.get("state"),
                "priority": issue.get("priority"), "assignees": assignees_list
            })
        return simplified_issues