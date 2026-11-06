import asyncio
import copy
from pathlib import Path
import tempfile
import unittest

from ariadne._util import loads
from ariadne.errors import Error
from ariadne.configuration import Configuration, ConfigurationStore
from ariadne.llm import Message, Response, ToolCall, Usage, Gateway
from ariadne.orchestrator import initialize, Options, ConversationStore, Orchestrator

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/system/fixtures/android-chat.sqlite"
PLAN = ROOT / "tests/system/fixtures/android-chat-tasks.json"


class Case(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="ariadne-python-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(Error) as raised:
            function(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)
        return raised.exception


class AsyncCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="ariadne-python-async-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    async def assert_async_code(self, code, operation):
        with self.assertRaises(Error) as raised:
            await operation
        self.assertEqual(raised.exception.code, code)
        return raised.exception


def configuration():
    return Configuration.from_dict(loads((ROOT / "examples/configuration.json").read_text()))


class Credentials:
    def resolve(self, reference):
        return "test-secret"


def reply(content="Hello"):
    return Response(Message.text("assistant", content), "stop", Usage(10, 5))


def calls(*values):
    from ariadne._util import dumps
    return Response(Message("assistant", tool_calls=[ToolCall(call_id, name, dumps(args)) for call_id, name, args in values]), "tool_calls")


class Script:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def gateway(self):
        gateway = Gateway(Credentials())
        gateway.register_adapter("openrouter", self)
        return gateway

    async def generate(self, binding, request, credentials, cancellation, emit):
        cancellation.check()
        self.requests.append((copy.deepcopy(binding), copy.deepcopy(request)))
        if not self.responses:
            raise AssertionError("Unexpected model call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if response.message.content:
            await emit({"type": "text_delta", "text": response.message.content})
        return copy.deepcopy(response)


class Harness:
    def __init__(self, root):
        self.root = Path(root)
        self.config = ConfigurationStore(self.root / "config")
        initialize(self.config.root, "example/model")
        self.conversation_path, self.task_path = self.root / "orchestrator.sqlite", self.root / "tasks.sqlite"

    def conversation(self, project="project"):
        with ConversationStore(self.conversation_path) as store:
            return store.create(self.config, project, "orchestrator", "A Python project")

    def engine(self):
        return Orchestrator(self.config, self.conversation_path, self.task_path)

    def options(self):
        return Options(self.config.root, self.task_path, "project", "orchestrator", "A Python project")

    def saved(self, session_id):
        with ConversationStore(self.conversation_path) as store:
            return store.get(session_id)
