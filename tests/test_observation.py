"""Offline evidence ingestion: no hidden credentials or live system access."""
import pytest

from worldfoundry.observation import (
    debezium_row_changes,
    directly_follows,
    otlp_span_events,
)


def test_otlp_exposes_span_order_but_not_sensitive_attributes():
    payload = {"resourceSpans": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "ticket-service"}}
        ]},
        "scopeSpans": [{"spans": [
            {"traceId": "abcd", "spanId": "2", "name": "authorize",
             "startTimeUnixNano": "200", "attributes": [
                 {"key": "authorization", "value": {"stringValue": "secret"}}
             ]},
            {"traceId": "abcd", "spanId": "1", "name": "create_ticket",
             "startTimeUnixNano": "100"},
        ]}],
    }]}
    events = otlp_span_events(payload)
    assert [event["activity"] for event in events] == ["create_ticket", "authorize"]
    assert all(event["service"] == "ticket-service" for event in events)
    assert "secret" not in str(events)
    graph = directly_follows(events)
    assert graph["edges"] == [{"from": "create_ticket", "to": "authorize", "count": 1}]
    assert graph["cases"] == 1


def test_debezium_import_requires_explicit_allowed_fields():
    message = {"payload": {
        "op": "u", "ts_ms": 123, "before": {"status": "pending", "ssn": "private"},
        "after": {"status": "approved", "ssn": "private"},
        "source": {"db": "private", "table": "tickets"},
    }}
    events = debezium_row_changes([message, {"payload": None}],
                                  fields={"status"})
    assert events == [{
        "operation": "u",
        "before": {"status": "pending"},
        "after": {"status": "approved"},
        "timestamp_ms": 123,
        "kind": "observed_row_change_not_agent_causality",
    }]
    assert "ssn" not in str(events)
    with pytest.raises(ValueError, match="allowlist"):
        debezium_row_changes([message], fields=set())


def test_process_graph_is_not_causal_claim():
    events = [
        {"case_id": "B", "activity": "done", "timestamp": 3},
        {"case_id": "A", "activity": "start", "timestamp": 1},
        {"case_id": "B", "activity": "start", "timestamp": 1},
        {"case_id": "A", "activity": "done", "timestamp": 2},
    ]
    graph = directly_follows(events)
    assert graph["cases"] == 2
    assert graph["edges"] == [{"from": "start", "to": "done", "count": 2}]
    assert graph["scope"] == "observed_directly_follows_only"
