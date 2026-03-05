import argparse
import sys
from src.interface.ariadne_tui import main as tui_main
from src.interface.init_cmd import setup_sandbox

def main():
    parser = argparse.ArgumentParser(description="Ariadne: Autonomous Software Lifecycle Engine")
    
    # We can keep 'tui' as an explicit command, or just flags. 
    # For now, let's keep it simple: running the script launches the TUI.
    # We can add a --help or version flag, but the primary mode is interactive.
    
    parser.add_argument("command", nargs="?", choices=["tui", "init"], default="tui", 
                        help="Launch the interactive Terminal UI (default) or initialize the sandbox (init)")

    args = parser.parse_args()

    if args.command == "tui":
        try:
            tui_main()
        except KeyboardInterrupt:
            print("\nGoodbye!")
            sys.exit(0)
    elif args.command == "init":
        setup_sandbox()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()