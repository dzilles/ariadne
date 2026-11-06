from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from ariadne._util import FileLock
from ariadne.errors import Error
from ariadne.configuration import ConfigurationStore
from ariadne.interaction import Interface, EventContext, Source
from ariadne.llm import Gateway, Cancellation
from ariadne.task import TaskStore, SearchQuery
from .engine import Orchestrator, notify
from .store import ConversationStore
from .tools import TaskTools


@dataclass
class Options:
    root: Path | str = Path(".ariadne")
    task_path: Path | str = Path("ariadne.sqlite")
    project_id: str = "default"
    profile_id: str = "orchestrator"
    project_summary: str = "Local project"

    def __post_init__(self):
        self.root, self.task_path = Path(self.root), Path(self.task_path)


class Application:
    """Headless command dispatcher. A future UI uses this API and Interface."""

    @classmethod
    async def start(cls, options=None, gateway=None):
        app = cls()
        app.options = options or Options()
        app.configuration = ConfigurationStore(app.options.root)
        app._lock = FileLock(app.options.root / ".application.lock", "APPLICATION_BUSY")
        try:
            config = app.configuration.load()[1]
            TaskTools.definitions(config, app.options.profile_id)
            if config.profiles[app.options.profile_id].component != "orchestrator":
                raise Error.invalid("Application requires an orchestrator profile")
            with ConversationStore(app.options.root / "orchestrator.sqlite") as store:
                store.recover_interrupted()
            with TaskStore(app.options.task_path):
                pass
            app.gateway, app.interface = gateway or Gateway(), Interface(128)
            app._active, app._notifications, app._closing = {}, set(), False
            app._dispatcher = asyncio.create_task(app._dispatch(), name="ariadne-dispatcher")
            return app
        except BaseException:
            app._lock.close()
            raise

    def conversations(self):
        with ConversationStore(self.options.root / "orchestrator.sqlite") as store:
            return store.list(self.options.project_id)

    def conversation(self, session_id):
        with ConversationStore(self.options.root / "orchestrator.sqlite") as store:
            conversation = store.get(session_id)
        if conversation.project_id != self.options.project_id:
            raise Error("FORBIDDEN", "Conversation belongs to another project")
        return conversation

    def create_conversation(self):
        with ConversationStore(self.options.root / "orchestrator.sqlite") as store:
            return store.create(self.configuration, self.options.project_id, self.options.profile_id, self.options.project_summary)

    def tasks(self):
        with TaskStore(self.options.task_path) as store:
            return store.orchestrator().search_tasks(SearchQuery(self.options.project_id, limit=200))

    def submit(self, session_id, payload):
        if self._closing:
            raise Error("DISCONNECTED", "Application is closing")
        self.conversation(session_id)
        return self.interface.submit(session_id, payload)

    async def _dispatch(self):
        try:
            while True:
                command = await self.interface.receive_command()
                try:
                    self.conversation(command.session_id)
                    kind = command.payload["type"]
                    if kind == "send_message":
                        if command.session_id in self._active or len(self._active) >= 16:
                            raise Error("BUSY", "This conversation is active or the concurrent-turn limit was reached")
                        cancellation = Cancellation()
                        task = asyncio.create_task(self._worker(command, cancellation), name=f"ariadne-turn-{command.command_id}")
                        self._active[command.session_id] = (command.command_id, cancellation, task)
                    elif kind == "cancel_run":
                        active = self._active.get(command.session_id)
                        if active is None or active[0] != command.payload["run_id"]:
                            raise Error("NOT_FOUND", "Run is not active in this conversation")
                        active[1].cancel()
                    else:
                        raise Error("UNSUPPORTED_OPERATION", "No workflow input handler is registered yet")
                except Error as exc:
                    task = asyncio.create_task(self._reject(command, exc))
                    self._notifications.add(task)
                    task.add_done_callback(self._notifications.discard)
        except (asyncio.CancelledError, Error):
            return

    async def _worker(self, command, cancellation):
        engine = Orchestrator(self.configuration, self.options.root / "orchestrator.sqlite", self.options.task_path)
        try:
            await engine.turn(command.session_id, command.command_id, command.payload["text"], self.gateway, self.interface, cancellation)
        except (Error, asyncio.CancelledError):
            pass  # turn() persisted the failure and published its terminal events.
        finally:
            self._active.pop(command.session_id, None)

    async def _reject(self, command, error):
        context = EventContext(command.command_id, command.command_id)
        source = Source("application", "dispatcher")
        await notify(self.interface, command.session_id, source, context, {"type": "error", "error": error.to_dict()})
        await notify(self.interface, command.session_id, source, context, {"type": "run_finished", "outcome": "rejected"})

    async def close(self):
        if self._closing:
            return
        self._closing = True
        self._dispatcher.cancel()
        await asyncio.gather(self._dispatcher, return_exceptions=True)
        workers = []
        for _, cancellation, task in self._active.values():
            cancellation.cancel()
            workers.append(task)
        await self.interface.close()  # Release publishers blocked by backpressure.
        pending = set()
        if workers:
            _, pending = await asyncio.wait(workers, timeout=5)
        for task in pending:
            task.cancel()
        await asyncio.gather(*workers, *self._notifications, return_exceptions=True)
        self._lock.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()
