"""Company-only Supabase PostgREST and Storage adapter.

Uses HTTPS APIs, not a database connection shared with end users. Tenant
ownership is verified at the WorldFoundry API before jobs are admitted.
Server credentials are only supplied to trusted worker/billing workloads.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

ALLOWED_TABLES = frozenset({
    "wf_projects", "wf_resources", "wf_managed_runs", "wf_managed_episodes",
    "wf_artifacts", "wf_managed_usage", "wf_billing_customers", "wf_billing_events",
})


class StorageError(RuntimeError):
    pass


class SupabaseStore:
    def __init__(self, url: str, service_key: str):
        if not url.startswith("https://") or not service_key:
            raise ValueError("Supabase HTTPS URL and server key are required")
        self.base = url.rstrip("/")
        self.key = service_key

    def _call(self, method: str, path: str, *, body: object | None = None,
              content_type: str = "application/json", raw: bool = False):
        headers = {
            "apikey": self.key, "Authorization": "Bearer " + self.key,
            "Content-Type": content_type, "Prefer": "return=representation",
        }
        payload = body if raw else json.dumps(body).encode() if body is not None else None
        request = Request(self.base + path, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=25) as response:
                data = response.read()
                return data if raw else json.loads(data) if data else []
        except HTTPError as exc:
            # Never include response bodies: they may contain protected data.
            raise StorageError("Supabase operation failed with HTTP " + str(exc.code)) from exc

    def _table(self, table: str) -> str:
        if table not in ALLOWED_TABLES:
            raise ValueError("Table not approved for internal adapter")
        return "/rest/v1/" + table

    def select(self, table: str, *, filters: dict[str, str] | None = None,
               columns: str = "*", order: str | None = None,
               limit: int | None = None) -> list[dict[str, Any]]:
        args = {"select": columns, **(filters or {})}
        if order:
            args["order"] = order
        if limit:
            args["limit"] = str(limit)
        return self._call("GET", self._table(table) + "?" + urlencode(args))

    def insert(self, table: str, values: dict[str, Any]) -> dict[str, Any]:
        rows = self._call("POST", self._table(table), body=values)
        return rows[0]

    def update(self, table: str, values: dict[str, Any],
               filters: dict[str, str]) -> list[dict[str, Any]]:
        if not filters:
            raise ValueError("Refusing unfiltered update")
        return self._call("PATCH", self._table(table) + "?" + urlencode(filters), body=values)

    def upload(self, bucket: str, key: str, data: bytes, media_type: str) -> None:
        if bucket != "wf-artifacts" or not key or len(data) > 5_000_000:
            raise ValueError("Invalid private artifact upload")
        path = "/storage/v1/object/" + quote(bucket, safe="") + "/" + quote(key, safe="/")
        self._call("POST", path, body=data, content_type=media_type, raw=True)
