"""Adapter contract for authorized snapshots of business applications."""
from __future__ import annotations

import copy
from typing import Any, Protocol


class ReadOnlyConnector(Protocol):
    def discover(self) -> dict[str, Any]: ...
    def snapshot(self) -> dict[str, Any]: ...


class JSONSnapshotConnector:
    """Import a company-supplied snapshot without accessing live systems."""

    def __init__(self, data: dict[str, Any]):
        if not isinstance(data, dict):
            raise TypeError("Snapshot must be a JSON object")
        self.data = copy.deepcopy(data)

    def discover(self) -> dict[str, Any]:
        return {"type": "json_snapshot", "resources": list(self.data),
                "live_writes": False}

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.data)
