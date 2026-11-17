"""Read-only, connector-backed local environment snapshots.

The caller explicitly provides the connector in Python. Each episode
fetches a snapshot once and simulates subsequent actions against a private
copy; actions never write back to the connected application.
"""
from __future__ import annotations

import copy
from typing import Any

from .declarative import DeclarativeEnvironment, overlay
from .environments import EnvironmentError
from .extensibility import ConnectorRegistry


class SnapshotEnvironment(DeclarativeEnvironment):
    id = "snapshot"
    name = "Connector Snapshot"
    description = "Authorized external data snapshot with local-only simulated actions."

    def __init__(self, settings: dict[str, Any], connectors: ConnectorRegistry) -> None:
        name = settings.get("connector")
        mount = settings.get("mount", "source")
        if not isinstance(name, str) or not name:
            raise EnvironmentError("Snapshot template requires a named connector")
        if not isinstance(mount, str) or not mount.isidentifier() or mount.startswith("_"):
            raise EnvironmentError("Snapshot mount must be a safe identifier")
        self._connectors = connectors
        self._connector_name = name
        self._mount = mount
        # Validate the configured source name up front. Credentials stay on
        # the developer-owned connector instance, not in resource metadata.
        self._connectors.get(name)
        if "initial_state" not in settings:
            raise EnvironmentError("Snapshot template requires initial_state")
        super().__init__(settings)

    def initial_state(self, seed: int) -> dict[str, Any]:
        base = super().initial_state(seed)
        source = self._connectors.get(self._connector_name).snapshot()
        if not isinstance(source, dict):
            raise EnvironmentError("Connector snapshot() must return a JSON object")
        merged = overlay(base, {self._mount: copy.deepcopy(source)})
        return merged
