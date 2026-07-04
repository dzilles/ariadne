import functools
from typing import Any, Callable

from src.ariadne.policies.evaluator import evaluate_tool_call


def get_work_item_store():
    # Backward-compatible helper for older scripts.
    from src.ariadne.infrastructure.container import DependencyRegistry

    return DependencyRegistry.get_work_item_tools().system


def get_ticket_system():
    """Backward-compatible alias for older tests and scripts."""
    return get_work_item_store()


def jit_vmodel_guard(func: Callable) -> Callable:
    """
    Decorator for mutating tools that checks active work-item context and
    V-model workflow rules before allowing execution.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        tool_name = func.__name__
        tool_args = _serialize_guard_args(args, kwargs)
        decision = evaluate_tool_call(
            tool_name,
            tool_args,
            check_user_permission=False,
            check_work_item=True,
        )
        if not decision.allowed:
            return decision.reason

        return func(*args, **kwargs)

    return wrapper


def _serialize_guard_args(args: tuple, kwargs: dict) -> dict:
    if kwargs:
        return dict(kwargs)

    # Decorated instance methods receive `self` as the first positional argument.
    positional = list(args[1:]) if args else []
    return {"args": positional}
