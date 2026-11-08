from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..client import WorldFoundry


def tools(client: WorldFoundry, episode_id: str) -> list[Callable[..., dict[str, Any]]]:
    """Return plain callables that Google ADK can wrap as function tools.

    This module intentionally has no hard ADK dependency. Applications using Google ADK can
    pass these callables to an Agent's ``tools`` list.
    """

    def worldfoundry_action(action: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform an action in the current WorldFoundry episode."""
        return client.act(episode_id, action, **(parameters or {})).to_dict()

    def worldfoundry_submit() -> dict[str, Any]:
        """Submit the current episode for deterministic validation."""
        return client.submit(episode_id).to_dict()

    return [worldfoundry_action, worldfoundry_submit]

