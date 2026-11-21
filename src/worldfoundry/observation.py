"""Safe, offline adapters for process evidence used in workflow reconstruction.

No network connections or live application writes occur in this module.
OTLP spans show observed calls; Debezium messages show observed database changes.
Neither proves the complete business rules or causal links.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


def otlp_span_events(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse OTLP/JSON traces into process-mining events.

    Intentionally discards span attributes, baggage, payloads and headers; these
    may contain credentials or personally identifying information.
    """
    if not isinstance(document, dict) or not isinstance(document.get("resourceSpans"), list):
        raise TypeError("OTLP/JSON document must contain resourceSpans")
    events: list[dict[str, Any]] = []
    for resource in document["resourceSpans"]:
        if not isinstance(resource, dict):
            raise TypeError("Invalid OTLP resource")
        service = ""
        for attr in resource.get("resource", {}).get("attributes", []):
            if attr.get("key") == "service.name":
                service = str(attr.get("value", {}).get("stringValue", ""))[:128]
        for scope in resource.get("scopeSpans", []):
            if not isinstance(scope, dict):
                raise TypeError("Invalid OTLP scope")
            for span in scope.get("spans", []):
                if not isinstance(span, dict):
                    raise TypeError("Invalid OTLP span")
                trace_id, name = span.get("traceId"), span.get("name")
                timestamp = span.get("startTimeUnixNano")
                if not isinstance(trace_id, str) or not isinstance(name, str):
                    raise ValueError("Trace span requires traceId and name")
                if timestamp is None:
                    raise ValueError("Trace span requires startTimeUnixNano")
                events.append({
                    "case_id": trace_id,
                    "activity": name[:128],
                    "timestamp": int(timestamp),
                    "span_id": str(span.get("spanId", "")),
                    "parent_span_id": str(span.get("parentSpanId", "")),
                    "service": service,
                })
    events.sort(key=lambda e: (e["case_id"], e["timestamp"], e["span_id"]))
    return events


def debezium_row_changes(messages: Iterable[Mapping[str, Any]], *,
                         fields: set[str]) -> list[dict[str, Any]]:
    """Extract a strict allowlist from already-exported CDC events.

    Does not retain Debezium metadata, tombstones, transaction ids or other
    columns. Caller must explicitly allow each data field.
    """
    if not isinstance(fields, set) or not fields or not all(
        isinstance(name, str) and name and len(name) <= 80 for name in fields
    ):
        raise ValueError("Specify a nonempty allowlist of row fields")
    results = []
    for message in messages:
        if not isinstance(message, Mapping):
            raise TypeError("CDC messages must be JSON objects")
        envelope = message.get("payload", message)
        if envelope is None:
            continue  # Tombstone emitted after a delete.
        if not isinstance(envelope, Mapping):
            raise TypeError("Invalid CDC envelope")
        operation = envelope.get("op")
        if operation not in ("c", "u", "d", "r"):
            continue  # Heartbeats, schema and transaction metadata are not row changes.
        before, after = envelope.get("before"), envelope.get("after")
        if any(row is not None and not isinstance(row, Mapping) for row in (before, after)):
            raise TypeError("CDC before/after must be objects or null")
        filtered = lambda row: {key: row[key] for key in sorted(fields) if row is not None
                                and key in row}
        results.append({
            "operation": operation,
            "before": filtered(before) if before is not None else None,
            "after": filtered(after) if after is not None else None,
            "timestamp_ms": envelope.get("ts_ms"),
            "kind": "observed_row_change_not_agent_causality",
        })
    return results


def directly_follows(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Count *observed* process transitions, not actual causal dependencies."""
    groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for event in events:
        if not isinstance(event, Mapping):
            raise TypeError("Process event must be an object")
        case, activity, timestamp = (event.get("case_id"), event.get("activity"),
                                     event.get("timestamp"))
        if not isinstance(case, str) or not case or not isinstance(activity, str):
            raise ValueError("Process event requires case_id and activity")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise ValueError("Process event requires numeric timestamp")
        groups[case].append((int(timestamp), activity))
    edges: Counter[tuple[str, str]] = Counter()
    starts: Counter[str] = Counter()
    ends: Counter[str] = Counter()
    for observations in groups.values():
        sequence = [activity for _, activity in sorted(observations)]
        starts[sequence[0]] += 1
        ends[sequence[-1]] += 1
        edges.update(zip(sequence, sequence[1:]))
    return {
        "cases": len(groups),
        "edges": [{"from": start, "to": end, "count": count}
                  for (start, end), count in sorted(edges.items())],
        "starts": dict(sorted(starts.items())),
        "ends": dict(sorted(ends.items())),
        "scope": "observed_directly_follows_only",
    }


def pm4py_discover(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Optional PM4Py directly-follows graph for timestamped case logs.

    PM4Py is imported only on demand, so the ordinary SDK stays dependency-free.
    """
    try:
        import pandas as pd
        import pm4py
    except ImportError as exc:
        raise RuntimeError('Install the optional "worldfoundry[process]" extra') from exc
    rows = []
    for event in events:
        if not all(key in event for key in ("case_id", "activity", "timestamp")):
            raise ValueError("Process mining requires case_id, activity and timestamp")
        rows.append({
            "case_id": str(event["case_id"]),
            "activity": str(event["activity"]),
            "timestamp": pd.to_datetime(int(event["timestamp"]), unit="ns", utc=True),
        })
    if not rows:
        return {"cases": 0, "edges": [], "starts": {}, "ends": {},
                "scope": "pm4py_observed_directly_follows"}
    frame = pm4py.format_dataframe(pd.DataFrame(rows), case_id="case_id",
                                   activity_key="activity", timestamp_key="timestamp")
    graph, start_activities, end_activities = pm4py.discover_dfg(frame)
    return {
        "cases": len({row["case_id"] for row in rows}),
        "edges": [{"from": start, "to": end, "count": count}
                  for (start, end), count in sorted(graph.items())],
        "starts": dict(start_activities),
        "ends": dict(end_activities),
        "scope": "pm4py_observed_directly_follows",
    }
