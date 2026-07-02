import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ariadne.ui.app import ChatUI


class FakeApprovalDialog:
    def __init__(self):
        self.visible = False
        self.shown = []
        self.hidden = 0

    def show(self, tool_name, args):
        self.visible = True
        self.shown.append((tool_name, args))

    def hide(self):
        self.visible = False
        self.hidden += 1

    def focus(self):
        pass


def test_tool_approvals_are_serialized_per_request(monkeypatch):
    async def scenario():
        ui = ChatUI()
        dialog = FakeApprovalDialog()
        monkeypatch.setattr(ui, "query_one", lambda _widget_type: dialog)
        monkeypatch.setattr(ui, "_focus_input", lambda: None)

        first = asyncio.create_task(ui.request_tool_approval("read_file", {"path": "a"}))
        await asyncio.sleep(0)
        second = asyncio.create_task(ui.request_tool_approval("write_file", {"path": "b"}))
        await asyncio.sleep(0)

        assert dialog.shown == [("read_file", {"path": "a"})]

        ui.on_approval_dialog_response(SimpleNamespace(result="yes"))
        assert await asyncio.wait_for(first, timeout=1) == "yes"
        await asyncio.sleep(0)

        assert dialog.shown == [
            ("read_file", {"path": "a"}),
            ("write_file", {"path": "b"}),
        ]

        ui.on_approval_dialog_response(SimpleNamespace(result="no"))
        assert await asyncio.wait_for(second, timeout=1) == "no"
        assert dialog.hidden == 2

    asyncio.run(scenario())
