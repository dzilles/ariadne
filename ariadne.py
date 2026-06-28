import argparse
import sys
from src.ariadne.ui.launcher import main as tui_main
from src.ariadne.cli.init import setup_sandbox
from src.ariadne.infrastructure.container import DependencyRegistry
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

def list_work_items():
    """List all work items from the configured store."""
    tools = DependencyRegistry.get_work_item_tools()
    work_items = tools.system.list_tickets()
    
    console = Console()
    table = Table(title="Ariadne Work Items (SQLite)")
    
    table.add_column("ID", justify="right", style="cyan", no_wrap=True)
    table.add_column("Title", style="white")
    table.add_column("Status", style="green")
    table.add_column("Type", style="magenta")
    
    for item in work_items:
        table.add_row(item.id, item.title, item.status, item.type.value)
        
    console.print(table)


def list_tickets():
    """Backward-compatible alias for list_work_items."""
    list_work_items()


def get_work_item_details(work_item_id: str):
    """Show detailed information for a specific work item."""
    tools = DependencyRegistry.get_work_item_tools()
    # Use the tool's get_ticket which already formats it nicely for LLMs,
    # or use the system directly for raw data.
    # Let's use the tool and wrap it in a Rich Panel for the CLI.
    details = tools.get_ticket(work_item_id)
    
    console = Console()
    console.print(Panel(details, title=f"Work Item #{work_item_id}", expand=False))


def get_ticket_details(ticket_id: str):
    """Backward-compatible alias for get_work_item_details."""
    get_work_item_details(ticket_id)


def create_work_item(title: str, description: str, work_item_type: str):
    """Create a new work item in the system."""
    from src.ariadne.work_items.models import WorkItemType

    tools = DependencyRegistry.get_work_item_tools()
    try:
        item_type = WorkItemType(work_item_type.capitalize())
    except ValueError:
        print(f"Error: Invalid work item type '{work_item_type}'. Allowed: {[t.value for t in WorkItemType]}")
        return

    item_id = tools.system.create_ticket(
        title=title,
        description=description,
        type=item_type,
        priority="medium"
    )
    print(f"Successfully created work item #{item_id}")


def create_ticket(title: str, description: str, ticket_type: str):
    """Backward-compatible alias for create_work_item."""
    create_work_item(title, description, ticket_type)

def main():
    parser = argparse.ArgumentParser(description="Ariadne: Autonomous Software Lifecycle Engine")
    
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # TUI command (default)
    subparsers.add_parser("tui", help="Launch the interactive Terminal UI")
    
    # Init command
    subparsers.add_parser("init", help="Initialize the sandbox")
    
    # Work item commands
    subparsers.add_parser("list-work-items", help="List all work items in a table view")
    subparsers.add_parser("list-tickets", help="Alias for list-work-items")
    
    get_parser = subparsers.add_parser("get-work-item", help="Show all information for a specific work item")
    get_parser.add_argument("work_item_id", help="The ID of the work item to display")

    get_ticket_parser = subparsers.add_parser("get-ticket", help="Alias for get-work-item")
    get_ticket_parser.add_argument("ticket_id", help="The ID of the work item to display")

    create_parser = subparsers.add_parser("create-work-item", help="Create a new work item")
    create_parser.add_argument("--title", required=True, help="Work item title")
    create_parser.add_argument("--description", required=True, help="Work item description")
    create_parser.add_argument("--type", default="Feature", help="Work item type (Feature, Bug, Task)")

    create_ticket_parser = subparsers.add_parser("create-ticket", help="Alias for create-work-item")
    create_ticket_parser.add_argument("--title", required=True, help="Work item title")
    create_ticket_parser.add_argument("--description", required=True, help="Work item description")
    create_ticket_parser.add_argument("--type", default="Feature", help="Work item type (Feature, Bug, Task)")

    args = parser.parse_args()

    # Default to TUI if no command provided
    if not args.command or args.command == "tui":
        try:
            tui_main()
        except KeyboardInterrupt:
            print("\nGoodbye!")
            sys.exit(0)
    elif args.command == "init":
        setup_sandbox()
    elif args.command == "list-work-items":
        list_work_items()
    elif args.command == "list-tickets":
        list_work_items()
    elif args.command == "get-work-item":
        get_work_item_details(args.work_item_id)
    elif args.command == "get-ticket":
        get_ticket_details(args.ticket_id)
    elif args.command == "create-work-item":
        create_work_item(args.title, args.description, args.type)
    elif args.command == "create-ticket":
        create_work_item(args.title, args.description, args.type)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
