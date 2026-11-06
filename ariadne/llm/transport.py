"""Native HTTP streaming on an I/O thread; no runtime HTTP dependencies."""
from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
import http.client
import socket
import ssl
import threading
from typing import AsyncIterator, Protocol
from urllib.parse import urlsplit

from ariadne.errors import Error
from .model import Cancellation


@dataclass(repr=False)
class HttpRequest:
    url: str
    bearer: str
    body: bytes
    timeout_ms: int = 120000


@dataclass
class Headers:
    status: int
    content_type: str


@dataclass
class Data:
    data: bytes


class HttpTransport(Protocol):
    def post(self, request: HttpRequest, cancellation: Cancellation) -> AsyncIterator[Headers | Data]: ...


class NativeHttpTransport:
    async def post(self, request, cancellation):
        cancellation.check()
        if len(request.body) > 8 * 1024 * 1024:
            raise Error.invalid("Model request exceeds 8 MiB")
        if not request.bearer or any(ord(c) < 32 or ord(c) == 127 for c in request.bearer):
            raise Error.invalid("Invalid API credential")
        parsed = urlsplit(request.url)
        loop = asyncio.get_running_loop()
        packets = asyncio.Queue(8)
        stopped = threading.Event()
        state_lock = threading.Lock()
        state = {"connection": None, "socket": None}

        def stop_io():
            stopped.set()
            with state_lock:
                active_socket = state["socket"]
            if active_socket:
                try:
                    active_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        def send(packet):
            if stopped.is_set():
                return False
            future = asyncio.run_coroutine_threadsafe(packets.put(packet), loop)
            while not stopped.is_set():
                try:
                    future.result(timeout=0.04)
                    return True
                except FutureTimeout:
                    continue
                except Exception:
                    return False
            future.cancel()
            return False

        def worker():
            connection = None
            try:
                timeout = request.timeout_ms / 1000
                if parsed.scheme == "https":
                    connection = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=timeout, context=ssl.create_default_context())
                elif parsed.scheme == "http":
                    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout)
                else:
                    send(Error.invalid("HTTP transport requires an HTTP(S) endpoint"))
                    return
                with state_lock:
                    state["connection"] = connection
                if stopped.is_set():
                    return
                connection.connect()
                with state_lock:
                    state["socket"] = connection.sock
                if stopped.is_set():
                    return
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
                connection.request("POST", path, body=request.body, headers={"Authorization": f"Bearer {request.bearer}", "Content-Type": "application/json", "Accept": "text/event-stream"})
                response = connection.getresponse()
                if not send(Headers(response.status, response.getheader("Content-Type", ""))):
                    return
                while not stopped.is_set():
                    chunk = response.read1(8192)
                    if not chunk:
                        send(None)
                        return
                    if not send(Data(chunk)):
                        return
            except (TimeoutError, socket.timeout):
                send(Error("TIMEOUT", "Model request timed out", True))
            except Exception:
                send(Error("TRANSPORT_ERROR", "HTTP connection failed or ended unexpectedly", True))
            finally:
                if connection:
                    connection.close()

        thread = threading.Thread(target=worker, name="ariadne-http", daemon=True)
        thread.start()
        cancel_task = asyncio.create_task(cancellation.wait())
        receive_task = None
        try:
            async with asyncio.timeout(request.timeout_ms / 1000):
                while True:
                    receive_task = asyncio.create_task(packets.get())
                    done, _ = await asyncio.wait((receive_task, cancel_task), return_when=asyncio.FIRST_COMPLETED)
                    if cancel_task in done:
                        cancellation.check()
                    packet = receive_task.result()
                    if packet is None:
                        return
                    if isinstance(packet, Error):
                        raise packet
                    yield packet
        except TimeoutError as exc:
            raise Error("TIMEOUT", "Model request timed out", True) from exc
        finally:
            stop_io()
            cancel_task.cancel()
            if receive_task and not receive_task.done():
                receive_task.cancel()
            await asyncio.gather(cancel_task, *([receive_task] if receive_task else []), return_exceptions=True)
            # DNS resolution cannot be interrupted by Python. Such an I/O thread
            # exits after connect/timeout and checks stopped before sending HTTP.
