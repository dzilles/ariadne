from headless_ariadne import HeadlessAriadne
from src.workflows.context import set_active_ticket_id

def run():
    a = HeadlessAriadne()
    
    # Simple instruction to trigger the improved system prompt behavior
    instruction = """
    Please perform a refinement pass on the architecture for Epic #15 (Ticket #19).
    
    Your goals:
    1. Finalize docs/design/ARCH-15.md according to our latest high-rigor standards.
    2. Read the comments on Ticket #19 and extract the Mermaid diagrams found there. You MUST include them in the document.
    3. Replace the generic '[PENDING LINK]' for the Requirement Link with the actual path to docs/requirements/REQ-15.md.
    4. Provide specific schemas (fields and types) for the Data Models (Conversation, BotResponse, StatusLine) and the 'get_state()' return dictionary.
    5. Attach the finalized document using 'add_link' and move the ticket forward.
    """
    
    set_active_ticket_id("19")
    
    print("🚀 Starting Architect Agent for high-rigor refinement pass...")
    response = a.chat_with_pause('Architect', instruction, max_tool_calls=15)
    
    print("\n--- Final Architect Agent Response (Paused) ---")
    print(response)

if __name__ == "__main__":
    run()

