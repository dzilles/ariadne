import copy

from ariadne._util import connect, new_id, now, dumps, loads, text, integer
from ariadne.errors import Error
from ariadne.llm import Binding, Message
from .model import Conversation, Entry, State


class ConversationStore:
    def __init__(self, path):
        self.db = connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS orchestrator_conversations(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,version INTEGER NOT NULL,updated_at TEXT NOT NULL,data TEXT NOT NULL CHECK(json_valid(data)))")
        self.db.execute("CREATE INDEX IF NOT EXISTS orchestrator_conversations_project ON orchestrator_conversations(project_id,updated_at)")

    @classmethod
    def open(cls, path): return cls(path)
    def close(self): self.db.close()
    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def create(self, configuration, project_id, profile_id="orchestrator", project_summary="Local project"):
        from .tools import TaskTools
        text(project_id, "project ID")
        text(project_summary, "project summary", empty=True)
        snapshot = configuration.create_snapshot()
        binding = Binding.from_snapshot(snapshot, profile_id)
        profile = snapshot.configuration.profiles[profile_id]
        if profile.component != "orchestrator":
            raise Error.invalid("Conversation requires an orchestrator profile")
        TaskTools.definitions(snapshot.configuration, profile_id)
        available = {"project_id": project_id, "project_summary": project_summary, "user_request": "Follow the user's messages in this conversation."}
        required = {v for name in profile.prompt_ids for v in snapshot.configuration.prompts[name].variables}
        if not required <= available.keys():
            raise Error.invalid("Unsupported orchestrator prompt input; use project_id, project_summary, or user_request")
        prompts = snapshot.render_profile(profile_id, {key: available[key] for key in required}).prompts
        instructions = "\n\n".join(p.text for p in prompts)
        instructions += "\n\nTask tools are scoped to the active project. Inspect stored facts before claiming changes. Agent execution, workflow execution, repository tools, and Git capture are not implemented. Define and inspect tasks and discuss configured workflows; do not claim to have run agents or tests."
        conversation = Conversation(new_id("session"), project_id, profile_id, snapshot.id, binding.model, binding.provider.id,
                                    "New conversation", 1, now(), entries=[Entry(new_id("message"), Message.text("system", instructions))])
        self.db.execute("INSERT INTO orchestrator_conversations VALUES(?,?,?,?,?)", (conversation.id, project_id, 1, conversation.updated_at, dumps(conversation)))
        return conversation

    def get(self, session_id):
        row = self.db.execute("SELECT data FROM orchestrator_conversations WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise Error("NOT_FOUND", "Conversation does not exist")
        return Conversation.from_dict(loads(row[0]))

    def list(self, project_id):
        return [Conversation.from_dict(loads(row[0])) for row in self.db.execute("SELECT data FROM orchestrator_conversations WHERE project_id=? ORDER BY updated_at DESC,id LIMIT 100", (project_id,))]

    def save(self, conversation):
        candidate = copy.deepcopy(conversation)
        candidate.version = integer(candidate.version + 1, "conversation version", 1)
        candidate.updated_at = now()
        row = self.db.execute("UPDATE orchestrator_conversations SET version=?,updated_at=?,data=? WHERE id=? AND version=?",
                              (candidate.version, candidate.updated_at, dumps(candidate), candidate.id, conversation.version))
        if row.rowcount != 1:
            raise Error("VERSION_CONFLICT", "Conversation changed; reload before continuing")
        conversation.__dict__.update(candidate.__dict__)

    def recover_interrupted(self):
        rows = self.db.execute("SELECT data FROM orchestrator_conversations WHERE json_extract(data,'$.state')='running'").fetchall()
        for row in rows:
            conversation = Conversation.from_dict(loads(row[0]))
            close_pending(conversation, "INTERRUPTED", "Execution was interrupted and may have performed changes. Inspect task records before retrying.")
            conversation.state, conversation.active_run_id = State.INTERRUPTED, None
            conversation.last_error = Error("INTERRUPTED", "Previous turn was interrupted; no tools were replayed").to_dict()
            self.save(conversation)
        return len(rows)


def close_pending(conversation, code, message):
    answered = {e.message.tool_call_id for e in conversation.entries if e.message.tool_call_id is not None}
    pending = [call for e in conversation.entries for call in e.message.tool_calls if call.id not in answered]
    for call in pending:
        conversation.entries.append(Entry(new_id("message"), Message.tool(call.id, {"ok": False, "error": {"code": code, "message": message}})))
