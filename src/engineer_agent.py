import os
import logging
from typing import Optional, Dict, Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from src.llm_factory import get_llm, load_env_config
from src.plane_client import PlaneInteraction
from src.config import settings

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EngineerAgent:
    """
    Engineer Agent responsible for converting Plane tickets into technical Markdown specifications.
    """

    def __init__(self):
        """
        Initialize the Engineer Agent.
        """
        load_env_config()
        self.llm = get_llm()

        # Load Agent-Specific Plane Key
        api_key = os.getenv("ENGINEER_AGENT_API_KEY")

        if api_key:
            logger.info("Using specific ENGINEER_AGENT_API_KEY for Plane interaction.")
        else:
            logger.error("ENGINEER_AGENT_API_KEY not found in environment. Agent-specific key is required.")
            raise ValueError("ENGINEER_AGENT_API_KEY is required but not set.")

        try:
            self.plane = PlaneInteraction(api_key=api_key)
        except Exception as e:
            logger.error(f"Failed to initialize PlaneInteraction: {e}")
            raise

    def _generate_spec_content(self, ticket_id: int, title: str, description: str) -> str:
        """
        Generates the markdown specification content using the LLM.
        """
        system_prompt = """You are a Senior Systems Engineer. You value precision, strict typing, and clear architectural boundaries.
Your task is to convert a User Story into a formal Technical Contract (Functional Specification).

Input:
- Ticket ID: {ticket_id}
- Title: {title}
- Description: {description}

Output Format (Strict Markdown):
# SPEC-{ticket_id}: {title}

## 1. Overview
(A concise 1-sentence summary of the technical goal)

## 2. Data Models
(Define the data structures. Use a table or bullet points. Specify Name, Type, and Constraints for each field.)

## 3. API Contract
(Define the interface. If it's a backend feature, define endpoints. If frontend, define Component Props/State.)
- **Endpoint/Component:** ...
- **Method/Input:** ...
- **Request/Props:** (JSON or Interface definition)
- **Response/Output:** (JSON or Interface definition + Status Codes)

## 4. Validation Rules
(List strict rules e.g., "File size < 5MB", "Email must be unique", "Date cannot be in the past".)

Constraint: Do NOT write the implementation code (Python/JS). Write the REQUIREMENTS for the code.
"""
        prompt = ChatPromptTemplate.from_template(system_prompt)
        chain = prompt | self.llm | StrOutputParser()

        logger.info(f"Generating spec for ticket {ticket_id}...")
        return chain.invoke({
            "ticket_id": ticket_id,
            "title": title,
            "description": description
        })

    def process_ticket(self, ticket_number: int) -> str:
        """
        Reads a Plane ticket, generates a spec, writes it to disk, and updates the ticket.

        Args:
            ticket_number (int): The sequence ID of the ticket.

        Returns:
            str: Path to the created specification file.
        """
        # 1. Fetch Ticket
        logger.info(f"Fetching ticket #{ticket_number}...")
        ticket = self.plane.get_issue_by_number(ticket_number)
        
        if isinstance(ticket, str) or not ticket:
            logger.error(f"Ticket {ticket_number} not found or error: {ticket}")
            return f"Error: {ticket}"

        title = ticket.get("name", "Unknown Title")
        description = ticket.get("description_html") or ticket.get("description", "")
        
        # 2. Generate Content
        spec_content = self._generate_spec_content(ticket_number, title, description)

        # 3. Write File
        project_path = settings.get("PROJECT_PATH", ".")
        docs_dir = os.path.join(project_path, "docs", "specs")
        
        if not os.path.exists(docs_dir):
            os.makedirs(docs_dir)
            logger.info(f"Created directory: {docs_dir}")

        filename = f"SPEC-{ticket_number}.md"
        file_path = os.path.join(docs_dir, filename)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(spec_content)
            logger.info(f"Saved spec to {file_path}")
        except Exception as e:
            logger.error(f"Failed to write file: {e}")
            raise

        # 4. Link in Plane
        comment_text = f"✅ Functional Spec created at `{file_path}`"
        
        result = self.plane.add_comment(ticket_number, comment_text)
        if result.startswith("Success"):
             logger.info("Posted update to Plane.")
        else:
             logger.warning(f"Failed to post comment to Plane: {result}")

        return file_path

if __name__ == "__main__":
    # Test Block
    try:
        agent = EngineerAgent()
        
        # You can change this ID to the one created by the PO Agent (likely 1)
        test_ticket_id = 1 
        
        print(f"Processing Ticket {test_ticket_id}...")
        result_path = agent.process_ticket(test_ticket_id)
        print(f"\nSuccess! Spec generated at: {result_path}")
        
    except Exception as e:
        print(f"Error: {e}")
