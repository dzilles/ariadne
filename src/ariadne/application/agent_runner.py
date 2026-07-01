"""Agent execution bridge for application-facing UI sessions."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from src.ariadne.runtime import run_manager
from src.ariadne.runtime.token_usage import (
    extract_token_usage,
    notify_active_work_item_token_usage,
)


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
    """Run an agent and update a response object with progress/results."""
    agent_name = agent.__class__.__name__
    run_state = run_manager.start_run(agent_name, message)
    try:
        if hasattr(agent, "agent_executor") and hasattr(agent, "chat_history"):
            await _handle_message_streaming(message, response, agent)
        else:
            await _handle_message_sync(message, response, agent)
        run_manager.finish_run(run_state.id)
    except Exception:
        run_manager.fail_run(run_state.id)
        raise


async def _handle_message_streaming(
    message: str,
    response: Any,
    agent: Any,
) -> None:
    """Handle a LangGraph-backed agent with event streaming when available."""
    response.thinking("Processing your request...")
    main_loop = asyncio.get_running_loop()
    import src.ariadne.tools.tool_wrapper as tool_wrapper

    tool_wrapper._event_loop = main_loop

    if hasattr(agent.agent_executor, "astream_events"):
        await _handle_message_events(message, response, agent)
        return

    def run_agent_sync():
        start_index = len(agent.chat_history)
        agent.chat_history.append(HumanMessage(content=message))
        inputs = {"messages": agent.chat_history}
        result = agent.agent_executor.invoke(inputs)
        return result, start_index

    try:
        task = main_loop.run_in_executor(None, run_agent_sync)
        while not task.done():
            if response.is_cancelled:
                run_manager.request_cancel()
            await asyncio.sleep(0.1)

        result, start_index = task.result()

        if "messages" in result:
            agent.chat_history = result["messages"]
            usage = extract_token_usage(agent.chat_history[start_index:])
            response.set_token_usage(usage)
            notify_active_work_item_token_usage(usage)

        if response.is_cancelled:
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
                response.error(str(content))
            else:
                response.complete(str(content))

    except asyncio.CancelledError:
        pass
    except Exception as e:
        error_msg = f"[System Error: {str(e)}]"
        agent.chat_history.append(AIMessage(content=error_msg))
        response.error(f"Agent error: {str(e)}")


async def _handle_message_events(
    message: str,
    response: Any,
    agent: Any,
) -> None:
    """Handle an agent through LangGraph events so cancellation is prompt."""
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
            if response.is_cancelled:
                run_manager.request_cancel()
                aclose = getattr(events, "aclose", None)
                if aclose:
                    await aclose()
                return

            kind = event.get("event", "")
            name = event.get("name", "")

            if kind == "on_chat_model_start":
                response.thinking("Model request started...")
            elif kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk is not None:
                    streamed_chunks.append(chunk)
                content = getattr(chunk, "content", None)
                text = _extract_text(content)
                if text:
                    if not started_response:
                        response.start_response()
                        started_response = True
                    response.append_response(text)
            elif kind == "on_tool_start":
                tool_name = name or "unknown"
                response.tool(tool_name, "Running...")
            elif kind == "on_chain_end":
                output = event.get("data", {}).get("output")
                if isinstance(output, dict) and "messages" in output:
                    final_state = output

        if response.is_cancelled:
            run_manager.request_cancel()
            _set_available_usage(response, streamed_chunks)
            return

        if final_state and "messages" in final_state:
            agent.chat_history = final_state["messages"]
        else:
            logger_state = getattr(agent, "chat_history", [])
            agent.chat_history = logger_state

        usage = extract_token_usage(agent.chat_history[start_index:])
        if not usage:
            usage = extract_token_usage(streamed_chunks)
        response.set_token_usage(usage)
        notify_active_work_item_token_usage(usage)
        _complete_from_history(response, agent.chat_history)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        error_msg = f"[System Error: {str(e)}]"
        agent.chat_history.append(AIMessage(content=error_msg))
        response.error(f"Agent error: {str(e)}")


async def _handle_message_sync(
    message: str,
    response: Any,
    agent: Any,
) -> None:
    """Handle an agent exposing only a synchronous chat() method."""
    response.thinking("Processing your request...")
    main_loop = asyncio.get_running_loop()
    import src.ariadne.tools.tool_wrapper as tool_wrapper

    tool_wrapper._event_loop = main_loop

    try:
        start_index = len(getattr(agent, "chat_history", []))
        task = main_loop.run_in_executor(None, agent.chat, message)

        while not task.done():
            if response.is_cancelled:
                run_manager.request_cancel()
            await asyncio.sleep(0.1)

        result = task.result()
        usage = extract_token_usage(getattr(agent, "chat_history", [])[start_index:])
        response.set_token_usage(usage)

        if response.is_cancelled:
            run_manager.request_cancel()
            return

        if result:
            if _is_error_response(result):
                response.error(result)
            else:
                response.complete(result)
        else:
            response.error("Agent returned empty response")

    except asyncio.CancelledError:
        pass
    except Exception as e:
        response.error(f"Agent error: {str(e)}")


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


def _set_available_usage(response: Any, usage_sources: list[Any]) -> None:
    """Attach any token usage metadata available before cancellation."""
    usage = extract_token_usage(usage_sources)
    if usage:
        response.set_token_usage(usage)
        notify_active_work_item_token_usage(usage)


def _complete_from_history(response: Any, chat_history: list[Any]) -> None:
    """Complete a response from the last AI message in chat history."""
    if not chat_history:
        response.error("Agent returned empty response")
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
        response.error(str(content))
    else:
        response.complete(str(content))
