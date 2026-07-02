import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ariadne.ui.message_display import (
    ActivityAnimation,
    DisplayMode,
    format_tool_call_detail,
    format_tool_result_preview,
    run_event_rule,
    tool_event_rule,
)


def test_run_event_display_rules_classify_lifecycle_noise():
    assert run_event_rule("thinking").mode == DisplayMode.TRANSIENT
    assert run_event_rule("thinking").animation == ActivityAnimation.WAVE
    assert run_event_rule("run_finished").mode == DisplayMode.HIDDEN


def test_tool_event_display_rules_keep_start_and_success_visible():
    assert tool_event_rule("start").mode == DisplayMode.PERSISTENT
    assert tool_event_rule("start").animation == ActivityAnimation.WAVE
    assert tool_event_rule("success").mode == DisplayMode.PERSISTENT


def test_tool_detail_formatter_shows_known_tool_parameters():
    assert (
        format_tool_call_detail("read_file", {"file_path": "src/app.py"})
        == "src/app.py"
    )
    assert (
        format_tool_call_detail(
            "search_files",
            {"directory": "src", "pattern": "*.py"},
        )
        == "src | pattern: *.py"
    )
    assert (
        format_tool_call_detail(
            "update_status",
            {"work_item_id": "42", "status": "Done"},
        )
        == "#42 -> Done"
    )


def test_tool_detail_formatter_handles_positional_and_unknown_args():
    assert (
        format_tool_call_detail("read_file", {"args": ["README.md"]})
        == "README.md"
    )
    assert (
        format_tool_call_detail("unknown_tool", {"query": "abc", "limit": 3})
        == "query: abc | limit: 3"
    )


def test_tool_result_preview_shows_output_seen_by_llm():
    assert format_tool_result_preview("line one\nline two", 100) == (
        "Output:\nline one\nline two"
    )
    assert format_tool_result_preview("abcdef", 4) == "Output:\nabc..."
    assert format_tool_result_preview("", 4) == "Output: <empty>"
