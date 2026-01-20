import os
import logging
from typing import List, Tuple, Any
from langchain_core.messages import messages_to_dict, messages_from_dict, HumanMessage

from langgraph.prebuilt import create_react_agent
from src.llm_factory import get_llm, load_env_config
from src.plane_client import PlaneInteraction
from src.pm_tools import ProjectManagementAgentTools

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ProductOwnerAgent:
    """
    Product Owner Agent responsible for translating feature requests into structured Agile tickets.
    Uses ProjectManagementAgentTools for backend interactions.
    """
    
    def __init__(self):
        """
        Initialize the Product Owner Agent with LLM and project management tools.
        """
        load_env_config()
        self.llm = get_llm()
        
        # Load Agent-Specific Plane Key (mapped to general PM backend)
        po_api_key = os.getenv("PO_AGENT_API_KEY")
        if not po_api_key:
            logger.error("PO_AGENT_API_KEY not found in environment.")
            raise ValueError("PO_AGENT_API_KEY is required.")

        # Initialize Backend Client
        try:
            self.client = PlaneInteraction(api_key=po_api_key)
            self.pm_tools = ProjectManagementAgentTools(self.client)
        except Exception as e:
            logger.error(f"Failed to initialize tools: {e}")
            raise

        # Register Tools from pm_tools instance
        self.tools = [
            self.pm_tools.create_ticket,
            self.pm_tools.create_sub_task,
            self.pm_tools.update_ticket,
            self.pm_tools.search_tickets,
            self.pm_tools.get_ticket_details,
            self.pm_tools.add_link,
            self.pm_tools.add_relation,
            self.pm_tools.attach_file,
            self.pm_tools.add_comment
        ]
        
        # Define the Agent
        self.agent_executor = create_react_agent(self.llm, self.tools, prompt=self._get_system_message())
        
        # Initialize chat history
        self.chat_history = []

    def get_history(self) -> List[dict]:
        """Returns the current chat history as a serializable list of dicts."""
        return messages_to_dict(self.chat_history)

    def load_history(self, history_data: List[dict]):
        """Loads chat history from a list of dicts."""
        try:
            self.chat_history = messages_from_dict(history_data)
            logger.info(f"Loaded {len(self.chat_history)} messages into history.")
        except Exception as e:
            logger.error(f"Failed to load history: {e}")
            raise

    def clear_history(self):
        """Clears the chat history."""
        self.chat_history = []
        logger.info("Chat history cleared.")

    def chat(self, user_input: str) -> str:
        """
        Interacts with the agent while maintaining chat history.
        """
        # Add user message to history
        self.chat_history.append(HumanMessage(content=user_input))
        
        # Invoke agent
        inputs = {"messages": self.chat_history}
        try:
            result = self.agent_executor.invoke(inputs)
        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            return f"[System Error: The AI agent encountered an issue: {str(e)}]"
        
        # Update history
        self.chat_history = result["messages"]
        
        # Get last message
        last_msg = self.chat_history[-1]
        content = last_msg.content
        
        # Handle list content
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, str): text_parts.append(part)
                elif isinstance(part, dict) and "text" in part: text_parts.append(part["text"])
            
            final_content = "".join(text_parts).strip()
            
            if not final_content and hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
                 return f"[Action Taken: {last_msg.tool_calls[0].get('name')}]"
            
            return final_content
            
        final_str = str(content)
        if not final_str.strip():
             return "[System Warning: The AI returned an empty response. This might be due to server overload or safety filters.]"
             
        return final_str

    def _get_system_message(self) -> str:
        """
        Returns the system message defining the agent persona and tool usage.
        """
        return """You are a strict and professional Product Owner. 
Your goal is to manage the product backlog and translate requirements into structured tickets.

Core Instructions:
1. Analyze user input. Answer questions directly or ask for clarification if a request is vague.
2. When creating/updating tickets, follow professional Agile standards.
3. You have access to various tools to interact with the project management system.

Backlog Management Rules:
- Create Ticket: For new features or bugs. Use structured HTML for descriptions (User Story + Acceptance Criteria).
- Sub-tasks: Break down complex tickets into smaller tasks.
- Updates: You can change status, assignees, dates, priority, labels, or parent tickets.
- Enrichment: Add links (URLs), relations (blocking/related), or attach local files.
- Comments: Add notes for clarification or updates.

When finding, updating or relating tickets:
- Always check the current state using 'get_ticket_details' if you are unsure about IDs or current properties.
- Use 'search_tickets' to find relevant tickets. You can filter by:
    - keyword (text search)
    - state_group ('backlog', 'started', 'completed')
    - priority ('high', 'urgent', etc.)
    - assignees (names/emails)
    - labels
    - specific state name (e.g. "In Progress")

Always report the exact result of your actions to the user.
"""

    def process_request(self, request: str) -> str:
        return self.chat(request)
