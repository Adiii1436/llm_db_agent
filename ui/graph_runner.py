from __future__ import annotations

from collections.abc import Callable
from typing import Any

try:
    from langgraph.types import Command
except Exception:  # pragma: no cover
    Command = None

from agent.graph import graph


def state_to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return dict(value)


def stream_graph(
    input_value: Any,
    config: dict[str, Any],
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    events: list[Any] = []
    for event in graph.stream(input_value, config=config, stream_mode="values"):
        events.append(event)
        if on_event:
            on_event(state_to_dict(event))
    last_state = state_to_dict(events[-1]) if events else state_to_dict(graph.get_state(config).values)
    return last_state, find_interrupt(config, events)


def resume_graph(
    payload: dict[str, Any],
    config: dict[str, Any],
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if Command is None:
        graph.update_state(config, payload)
        return stream_graph(None, config, on_event=on_event)
    return stream_graph(Command(resume=payload), config, on_event=on_event)


def find_interrupt(config: dict[str, Any], events: list[Any] | None = None) -> dict[str, Any] | None:
    for event in events or []:
        event_dict = state_to_dict(event)
        interrupt_value = _interrupt_payload(event_dict.get("__interrupt__"))
        if interrupt_value:
            return interrupt_value

    snapshot = graph.get_state(config)
    direct = _interrupt_payload(getattr(snapshot, "interrupts", None))
    if direct:
        return direct

    for task in getattr(snapshot, "tasks", ()) or ():
        task_interrupt = _interrupt_payload(getattr(task, "interrupts", None))
        if task_interrupt:
            return task_interrupt
    return None


def _interrupt_payload(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    interrupts = value if isinstance(value, (list, tuple)) else (value,)
    for item in interrupts:
        payload = getattr(item, "value", item)
        if isinstance(payload, dict):
            return payload
    return None
