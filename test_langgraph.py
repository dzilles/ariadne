import sys
import os
sys.path.append(os.getcwd())
from src.ariadne.agents.orchestrator_agent import OrchestratorAgent


def main():
    agent = OrchestratorAgent()
    print(agent.chat("Hello, what is your mission?"))


if __name__ == "__main__":
    main()
