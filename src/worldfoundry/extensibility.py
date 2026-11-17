"""Developer-owned local environment and connector extension points.

Plugins run in the *developer's Python process*. Never import third-party
Python plugins on shared hosted infrastructure or from an untrusted dataset.
"""
from __future__ import annotations

import importlib
import re
from collections.abc import Callable, Mapping
from typing import Any, Protocol, runtime_checkable

from .environments import EnvironmentError, SupportDeskEnvironment

_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


@runtime_checkable
class EnvironmentPlugin(Protocol):
    """Contract for user-defined stateful workflow simulation environments."""

    id: str
    name: str
    description: str
    tasks: tuple[str, ...]
    instruction: str

    def initial_state(self, seed: int) -> dict[str, Any]: ...
    def actions(self) -> tuple[Any, ...]: ...
    def perform(self, state: dict[str, Any], action: str,
                params: dict[str, Any]) -> dict[str, Any]: ...
    def validate(self, state: dict[str, Any]) -> Any: ...


class TemplateRegistry:
    """Maps stable template names to local Python factories.

    Template factories receive a JSON-serializable settings dict. Register
    them on every process that opens the environment, including the CLI
    and local REST server.
    """

    def __init__(self) -> None:
        self._providers: dict[str, Callable[[dict[str, Any]], EnvironmentPlugin]] = {
            "support-desk": lambda settings: SupportDeskEnvironment(),
        }
        self._descriptions: dict[str, str] = {
            "support-desk": SupportDeskEnvironment.description,
        }

    def register(self, name: str,
                 factory: Callable[[dict[str, Any]], EnvironmentPlugin] | EnvironmentPlugin,
                 *, description: str = "", replace: bool = False) -> None:
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise EnvironmentError("Template names must be lowercase letters, digits, - or _")
        if name in self._providers and not replace:
            raise EnvironmentError(f"Template already registered: {name}")
        if isinstance(factory, EnvironmentPlugin):
            # The caller owns the instance and must keep execution state in
            # the episode's state dict, not on this shared plugin object.
            provider = lambda settings: factory
        elif callable(factory):
            provider = factory
        else:
            raise TypeError("Template must implement EnvironmentPlugin or be a factory")
        self._providers[name] = provider
        self._descriptions[name] = description

    def make(self, name: str, settings: dict[str, Any] | None = None) -> EnvironmentPlugin:
        if name not in self._providers:
            raise EnvironmentError(
                f"Unknown environment template: {name}. "
                "Register a Python plugin or use the declarative template."
            )
        config = settings or {}
        if not isinstance(config, dict):
            raise EnvironmentError("Template settings must be a JSON object")
        instance = self._providers[name](config)
        if not isinstance(instance, EnvironmentPlugin):
            raise EnvironmentError(f"Template {name} does not implement EnvironmentPlugin")
        if not instance.tasks or not instance.actions():
            raise EnvironmentError(f"Template {name} must declare tasks and actions")
        return instance

    def list(self) -> list[dict[str, str]]:
        return [{"id": name, "description": self._descriptions.get(name, "")}
                for name in sorted(self._providers)]


class ConnectorRegistry:
    """Explicit, developer-injected connector objects.

    Connectors can wrap arbitrary authorized APIs and databases. WorldFoundry
    never retrieves credentials, executes live writes, or invokes a connector
    without the developer's own environment/plugin requesting it.
    """

    def __init__(self) -> None:
        self._connectors: dict[str, Any] = {}

    def register(self, name: str, connector: Any, *, replace: bool = False) -> None:
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError("Invalid connector name")
        if name in self._connectors and not replace:
            raise ValueError(f"Connector already registered: {name}")
        if not hasattr(connector, "snapshot") or not callable(connector.snapshot):
            raise TypeError("Connector must implement snapshot()")
        self._connectors[name] = connector

    def get(self, name: str) -> Any:
        try:
            return self._connectors[name]
        except KeyError as exc:
            raise KeyError(f"Connector not registered: {name}") from exc

    def list(self) -> list[str]:
        return sorted(self._connectors)


def load_local_plugins(client: Any, modules: list[str]) -> None:
    """Explicit opt-in Python import, only for local programs/CLI/REST server."""
    seen: set[str] = set()
    for name in modules:
        if not name or name in seen:
            continue
        if not re.fullmatch(r"[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*", name):
            raise ValueError("Plugin must be a Python module import path")
        seen.add(name)
        module = importlib.import_module(name)
        register = getattr(module, "register", None)
        if not callable(register):
            raise TypeError(f"Plugin {name} must export register(worldfoundry_client)")
        register(client)
