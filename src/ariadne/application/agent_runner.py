"""Agent execution bridge for application-facing UI sessions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from src.ariadne.runtime import run_manager
from src.ariadne.runtime.token_usage import (
    extract_token_usage,
    notify_active_work_item_token_usage,
)
from src.ariadne.application.ui_contract import RunEvent, TokenUsage


ERROR_PATTERNS = [
    "[System Error:",
    "[System Warning:",
    "[Error:",
    "[Action Taken:",
]


def _is_error_response(result: str) -> bool:
    """Check if the agent's response indicates an error."""
    if not result:
        return True
    return any(result.strip().startswith(pattern) for pattern in ERROR_PATTERNS)


async def handle_message(
    message: str,
    response: Any,
    agent: Any,
) -> None:
    """Compatibility wrapper that maps run events to a response object."""
    await run_agent(
        message,
        agent,
        emit=lambda event: _apply_event_to_response(response, event),
        is_cancelled=lambda: bool(getattr(response, "is_cancelled", False)),
    )


async def run_agent(
    message: str,
    agent: Any,
    *,
    emit: Callable[[RunEvent], None],
    is_cancelled: Callable[[], bool],
) -> None:
    """Run an agent and emit structured execution events."""
    agent_name = agent.__class__.__name__
    run_state = run_manager.start_run(agent_name, message)
    emit(
        RunEvent(
            "run_started",
            detail=f"{agent_name} started",
            run_id=run_state.id,
            agent_name=agent_name,
        )
    )
    try:
        if hasattr(agent, "agent_executor") and hasattr(agent, "chat_history"):
            await _handle_message_streaming(message, agent, emit, is_cancelled)
        else:
            await _handle_message_sync(message, agent, emit, is_cancelled)
        duration = _duration_seconds(run_state.started_at)
        if run_state.cancel_requested:
            emit(
                RunEvent(
                    "cancelled",
                    detail=f"Cancelled after {_format_duration(duration)}",
                    run_id=run_state.id,
                    agent_name=agent_name,
                    duration_seconds=duration,
                )
            )
        else:
            emit(
                RunEvent(
                    "run_finished",
                    detail=f"Finished in {_format_duration(duration)}",
                    run_id=run_state.id,
                    agent_name=agent_name,
                    duration_seconds=duration,
                )
            )
        run_manager.finish_run(run_state.id)
    except Exception:
        run_manager.fail_run(run_state.id)
        raise


async def _handle_message_streaming(
    message: str,
    agent: Any,
    emit: Callable[[RunEvent], None],
    is_cancelled: Callable[[], bool],
) -> None:
    """Handle a LangGraph-backed agent with event streaming when available."""
    emit(RunEvent("thinking"))
    main_loop = asyncio.get_running_loop()
    import src.ariadne.tools.tool_wrapper as tool_wrapper

    tool_wrapper._event_loop = main_loop

    if hasattr(agent.agent_executor, "astream_events"):
        await _handle_message_events(message, agent, emit, is_cancelled)
        return

    def run_agent_sync():
        from langchain_core.messages import HumanMessage

        start_index = len(agent.chat_history)
        agent.chat_history.append(HumanMessage(content=message))
        inputs = {"messages": agent.chat_history}
        result = agent.agent_executor.invoke(inputs)
        return result, start_index

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            task = main_loop.run_in_executor(executor, run_agent_sync)
            while not task.done():
                if is_cancelled():
                    run_manager.request_cancel()
                await asyncio.sleep(0.1)

            result, start_index = task.result()

        if "messages" in result:
            agent.chat_history = result["messages"]
            usage = extract_token_usage(agent.chat_history[start_index:])
            _emit_usage(emit, usage)

        if is_cancelled():
            run_manager.request_cancel()
            return

        if agent.chat_history:
            last_msg = agent.chat_history[-1]
            content = last_msg.content
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, str):
                        text_parts.append(part)
                    elif isinstance(part, dict) and "text" in part:
                        text_parts.append(part["text"])
                final_str = "".join(text_parts).strip()
                content = final_str if final_str else "[Action Performed]"

            if _is_error_response(str(content)):
                emit(RunEvent("error", message=str(content)))
            else:
                emit(RunEvent("complete", message=str(content)))

    except asyncio.CancelledError:
        pass
    except Exception as e:
        from langchain_core.messages import AIMessage

        error_msg = f"[System Error: {str(e)}]"
        agent.chat_history.append(AIMessage(content=error_msg))
        emit(RunEvent("error", message=f"Agent error: {str(e)}"))


async def _handle_message_events(
    message: str,
    agent: Any,
    emit: Callable[[RunEvent], None],
    is_cancelled: Callable[[], bool],
) -> None:
    """Handle an agent through LangGraph events so cancellation is prompt."""
    from langchain_core.messages import HumanMessage

    start_index = len(agent.chat_history)
    agent.chat_history.append(HumanMessage(content=message))
    inputs = {"messages": agent.chat_history}
    final_state = None
    started_response = False
    streamed_chunks = []

    try:
        events = agent.agent_executor.astream_events(
            inputs,
            version="v2",
            config=getattr(agent.agent_executor, "config", None),
        )

        async for event in events:
            if is_cancelled():
                run_manager.request_cancel()
                _set_available_usage(emit, streamed_chunks)
                return

            kind = event.get("event", "")
            name = event.get("name", "")

            if kind == "on_chat_model_start":
                emit(RunEvent("thinking"))
            elif kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk is not None:
                    streamed_chunks.append(chunk)
                content = getattr(chunk, "content", None)
                text = _extract_text(content)
                if text:
                    if not started_response:
                        emit(RunEvent("response_start"))
                        started_response = True
                    emit(RunEvent("response_delta", message=text))
            elif kind == "on_tool_start":
                tool_name = name or "unknown"
                tool_args = event.get("data", {}).get("input")
                if not isinstance(tool_args, dict):
                    tool_args = {}
                emit(
                    RunEvent(
                        "tool_start",
                        tool_name=tool_name,
                        detail="Running...",
                        args=tool_args,
                    )
                )
            elif kind == "on_chain_end":
                output = event.get("data", {}).get("output")
                if isinstance(output, dict) and "messages" in output:
                    final_state = output

        if is_cancelled():
            run_manager.request_cancel()
            _set_available_usage(emit, streamed_chunks)
            return

        if final_state and "messages" in final_state:
            agent.chat_history = final_state["messages"]
        else:
            logger_state = getattr(agent, "chat_history", [])
            agent.chat_history = logger_state

        usage = extract_token_usage(agent.chat_history[start_index:])
        if not usage:
            usage = extract_token_usage(streamed_chunks)
        _emit_usage(emit, usage)
        _complete_from_history(emit, agent.chat_history)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        from langchain_core.messages import AIMessage

        error_msg = f"[System Error: {str(e)}]"
        agent.chat_history.append(AIMessage(content=error_msg))
        emit(RunEvent("error", message=f"Agent error: {str(e)}"))


async def _handle_message_sync(
    message: str,
    agent: Any,
    emit: Callable[[RunEvent], None],
    is_cancelled: Callable[[], bool],
) -> None:
    """Handle an agent exposing only a synchronous chat() method."""
    emit(RunEvent("thinking"))
    main_loop = asyncio.get_running_loop()
    import src.ariadne.tools.tool_wrapper as tool_wrapper

    tool_wrapper._event_loop = main_loop

    try:
        start_index = len(getattr(agent, "chat_history", []))
        with ThreadPoolExecutor(max_workers=1) as executor:
            task = main_loop.run_in_executor(executor, agent.chat, message)

            while not task.done():
                if is_cancelled():
                    run_manager.request_cancel()
                await asyncio.sleep(0.1)

            result = task.result()
        usage = extract_token_usage(getattr(agent, "chat_history", [])[start_index:])
        _emit_usage(emit, usage)

        if is_cancelled():
            run_manager.request_cancel()
            return

        if result:
            if _is_error_response(result):
                emit(RunEvent("error", message=result))
            else:
                emit(RunEvent("complete", message=result))
        else:
            emit(RunEvent("error", message="Agent returned empty response"))

    except asyncio.CancelledError:
        pass
    except Exception as e:
        emit(RunEvent("error", message=f"Agent error: {str(e)}"))


def _extract_text(content: Any) -> str:
    """Extract display text from provider-specific stream content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                text_parts.append(str(part["text"]))
        return "".join(text_parts)
    return ""


def _duration_seconds(started_at: datetime) -> float:
    """Return elapsed seconds since the run started."""
    return max(0.0, (datetime.now() - started_at).total_seconds())


def _format_duration(seconds: float) -> str:
    """Format elapsed seconds for the UI."""
    if seconds < 10:
        return f"{seconds:.1f}s"
    return f"{seconds:.0f}s"


def _set_available_usage(
    emit: Callable[[RunEvent], None],
    usage_sources: list[Any],
) -> None:
    """Attach any token usage metadata available before cancellation."""
    usage = extract_token_usage(usage_sources)
    _emit_usage(emit, usage)


def _emit_usage(emit: Callable[[RunEvent], None], usage: dict[str, int] | None) -> None:
    """Emit token usage and notify active work item listeners."""
    if usage:
        token_usage = TokenUsage.from_dict(usage)
        if token_usage:
            emit(RunEvent("token_usage", usage=token_usage))
        notify_active_work_item_token_usage(usage)


def _complete_from_history(
    emit: Callable[[RunEvent], None],
    chat_history: list[Any],
) -> None:
    """Complete a response from the last AI message in chat history."""
    if not chat_history:
        emit(RunEvent("error", message="Agent returned empty response"))
        return

    last_msg = chat_history[-1]
    content = getattr(last_msg, "content", "")

    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                text_parts.append(str(part["text"]))
        content = "".join(text_parts).strip() or "[Action Performed]"

    if _is_error_response(str(content)):
        emit(RunEvent("error", message=str(content)))
    else:
        emit(RunEvent("complete", message=str(content)))


def _apply_event_to_response(response: Any, event: RunEvent) -> None:
    """Apply a run event to the legacy response object."""
    if event.type == "run_started":
        return
    elif event.type == "run_finished":
        return
    elif event.type == "thinking":
        response.thinking()
    elif event.type == "response_start":
        response.start_response()
    elif event.type == "response_delta":
        response.append_response(event.message)
    elif event.type == "tool_start":
        if hasattr(response, "activity"):
            response.activity(f"Tool: {event.tool_name}", event.detail)
        response.tool(event.tool_name, event.detail)
    elif event.type == "token_usage" and event.usage:
        response.set_token_usage(event.usage.to_dict())
    elif event.type == "complete":
        response.complete(event.message)
    elif event.type == "error":
        response.error(event.message)
    elif event.type == "cancelled":
        if not getattr(response, "is_cancelled", False):
            response.cancel()
