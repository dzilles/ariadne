import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description="Ariadne: Autonomous Software Lifecycle Engine")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Phase command
    phase_parser = subparsers.add_parser("phase", help="Execute a V-Model phase")
    phase_parser.add_argument("name", choices=[
        "gather", "analysis", "software-design", "module-design",
        "code", "unit-test", "integration-test", "system-test", "acceptance"
    ], help="Phase name")
    phase_parser.add_argument("--ticket", required=True, help="Plane ticket ID")

    # Review command
    review_parser = subparsers.add_parser("review", help="Review a phase artifact")
    review_parser.add_argument("--human", action="store_true", help="Human review")
    review_parser.add_argument("--approve", action="store_true", help="Approve artifact")
    review_parser.add_argument("--file", required=True, help="File to review")

    # Complete command
    complete_parser = subparsers.add_parser("complete", help="Finalize a ticket")
    complete_parser.add_argument("--ticket", required=True, help="Plane ticket ID")

    # Start command
    subparsers.add_parser("start", help="Start the Plane Docker environment")

    # Chat command
    subparsers.add_parser("chat", help="Start the interactive agent chat interface")

    args = parser.parse_args()

    if args.command == "phase":
        print(f"Executing phase '{args.name}' for ticket {args.ticket}...")
        # Implementation logic will go here
    elif args.command == "review":
        status = "approved" if args.approve else "rejected"
        print(f"Reviewing {args.file} (Human: {args.human}) - Status: {status}")
        # Implementation logic will go here
    elif args.command == "complete":
        print(f"Completing lifecycle for ticket {args.ticket}...")
        # Implementation logic will go here
    elif args.command == "start":
        print("Starting Plane environment...")
        import subprocess
        try:
            subprocess.run([sys.executable, "src/setup_plane.py"], check=True)
        except subprocess.CalledProcessError:
            print("Failed to start Plane environment.")
            sys.exit(1)
    elif args.command == "chat":
        from src.user_interface import main as chat_main
        chat_main()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
