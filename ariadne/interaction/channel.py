from __future__ import annotations

import asyncio
import copy
from collections import deque
from dataclasses import dataclass

from ariadne._util import new_id, integer, text
from ariadne.errors import Error
from .model import Command, Source, EventContext, Event, validate_command, validate_event


class _Mailbox:
    def __init__(self, capacity):
        self.capacity, self.queue, self.closed = capacity, deque(), False
        self.condition = asyncio.Condition()

    async def close(self):
        async with self.condition:
            self.closed = True
            self.queue.clear()
            self.condition.notify_all()


@dataclass
class _Session:
    sequence: int = 0
    mailbox: _Mailbox | None = None


class Subscription:
    def __init__(self, session, mailbox):
        self._session, self._mailbox = session, mailbox

    async def recv(self):
        box = self._mailbox
        async with box.condition:
            await box.condition.wait_for(lambda: box.queue or box.closed)
            if box.closed:
                raise Error("DISCONNECTED", "Event subscription is closed")
            event = box.queue.popleft()
            box.condition.notify_all()
            return event

    async def close(self):
        await self._mailbox.close()
        if self._session.mailbox is self._mailbox:
            self._session.mailbox = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.recv()
        except Error as exc:
            if exc.code == "DISCONNECTED":
                raise StopAsyncIteration from exc
            raise


class Interface:
    """One event subscriber per session; commands and events remain temporary.

    Create/use this interface inside one event loop. Other modules share the same
    instance. Bounded per-session mailboxes isolate slow subscribers.
    """

    def __init__(self, capacity=128):
        integer(capacity, "channel capacity", 1)
        self.capacity, self._closed = capacity, False
        self._commands = asyncio.Queue(capacity)
        self._sessions = {}

    def submit(self, session_id, payload):
        self._check()
        text(session_id, "session ID")
        validate_command(payload)
        command = Command(new_id("command"), session_id, copy.deepcopy(payload))
        try:
            self._commands.put_nowait(command)
        except asyncio.QueueFull as exc:
            raise Error("BUSY", "Command queue is full; retry later") from exc
        return command.command_id

    async def receive_command(self):
        self._check()
        command = await self._commands.get()
        self._check()
        return command

    def subscribe(self, session_id):
        self._check()
        text(session_id, "session ID")
        session = self._sessions.setdefault(session_id, _Session())
        if session.mailbox is not None:
            raise Error("ALREADY_SUBSCRIBED", "This session already has a subscriber")
        mailbox = _Mailbox(self.capacity)
        session.mailbox = mailbox
        return Subscription(session, mailbox)

    async def publish(self, session_id, source, context, payload):
        self._check()
        validate_event(payload)
        if not isinstance(source, Source) or not isinstance(context, EventContext):
            raise Error.invalid("Events need Source and EventContext values")
        text(source.component, "source component")
        text(source.instance_id, "source instance")
        for key, value in context.to_dict().items():
            if value is not None:
                text(value, key)
        session = self._sessions.get(session_id)
        if session is None or session.mailbox is None:
            raise Error("NO_SUBSCRIBER", "No frontend is subscribed to this session")
        box = session.mailbox
        async with box.condition:
            await box.condition.wait_for(lambda: len(box.queue) < box.capacity or box.closed)
            if box.closed:
                raise Error("NO_SUBSCRIBER", "Subscriber disconnected")
            session.sequence += 1
            box.queue.append(Event(new_id("event"), session_id, session.sequence, copy.deepcopy(source), copy.deepcopy(context), copy.deepcopy(payload)))
            box.condition.notify_all()

    def _check(self):
        if self._closed:
            raise Error("DISCONNECTED", "Application interface is closed")

    async def close(self):
        if self._closed:
            return
        self._closed = True
        for session in self._sessions.values():
            if session.mailbox:
                await session.mailbox.close()
                session.mailbox = None
        try:
            self._commands.put_nowait(None)
        except asyncio.QueueFull:
            pass
