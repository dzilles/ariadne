import logging
from typing import Any, Dict, Type, TypeVar

from src.ariadne.tools.file_tools import FileAgentTools
from src.ariadne.tools.git_tools import GitAgentTools
from src.ariadne.tools.shell_tools import ShellAgentTools
from src.ariadne.work_items.adapters.sqlite import SQLiteWorkItemStore
from src.ariadne.work_items.tools import WorkItemTools

logger = logging.getLogger(__name__)

T = TypeVar("T")


class DependencyRegistry:
    """
    Central dependency registry to prevent duplicate instantiations of clients
    and tools across multiple agents.
    """

    _instances: Dict[Any, Any] = {}

    @classmethod
    def get(cls, class_type: Type[T], *args, **kwargs) -> T:
        """
        Retrieve a singleton instance of the requested class.

        Arguments are part of the cache key, so differently configured
        instances remain separate.
        """
        key = (class_type, args, frozenset(kwargs.items()))
        if key not in cls._instances:
            logger.debug(f"Initializing new instance of {class_type.__name__}")
            cls._instances[key] = class_type(*args, **kwargs)
        return cls._instances[key]

    @classmethod
    def get_sqlite_work_item_store(cls, db_path: str = "ariadne_tickets.db") -> SQLiteWorkItemStore:
        return cls.get(SQLiteWorkItemStore, db_path=db_path)

    @classmethod
    def get_sqlite_ticket_system(cls, db_path: str = "ariadne_tickets.db") -> SQLiteWorkItemStore:
        return cls.get_sqlite_work_item_store(db_path=db_path)

    @classmethod
    def get_file_tools(cls) -> FileAgentTools:
        return cls.get(FileAgentTools)

    @classmethod
    def get_git_tools(cls) -> GitAgentTools:
        return cls.get(GitAgentTools)

    @classmethod
    def get_shell_tools(cls) -> ShellAgentTools:
        return cls.get(ShellAgentTools)

    @classmethod
    def get_work_item_tools(cls) -> WorkItemTools:
        system = cls.get_sqlite_work_item_store()
        return cls.get(WorkItemTools, system)

    @classmethod
    def get_ticket_tools(cls) -> WorkItemTools:
        return cls.get_work_item_tools()

    @classmethod
    def clear(cls):
        """Clear the registry, mainly for tests."""
        cls._instances.clear()
