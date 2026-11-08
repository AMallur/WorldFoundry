from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import ActionSpec, ValidationCheck, ValidationResult


class EnvironmentError(ValueError):
    pass


class SupportDeskEnvironment:
    id = "support-desk"
    name = "Support Desk"
    description = "A simulated customer support queue with mutable tickets and audit-safe actions."
    tasks = ("incident-triage",)

    instruction = (
        "Triage the Acme Corp production outage in ticket TCK-100. Make it critical, assign "
        "it to the on-call engineer, send the customer a reply that acknowledges the outage "
        "and mentions an incident, then resolve the ticket."
    )

    action_specs = (
        ActionSpec("list_tickets", "List tickets, optionally filtered by status.", {"status": {"type": "string"}}),
        ActionSpec(
            "get_ticket",
            "Read a ticket.",
            {"ticket_id": {"type": "string"}},
            ("ticket_id",),
        ),
        ActionSpec(
            "set_priority",
            "Change a ticket priority.",
            {"ticket_id": {"type": "string"}, "priority": {"type": "string", "enum": ["low", "normal", "high", "critical"]}},
            ("ticket_id", "priority"),
        ),
        ActionSpec(
            "assign",
            "Assign a ticket to a support user.",
            {"ticket_id": {"type": "string"}, "assignee": {"type": "string"}},
            ("ticket_id", "assignee"),
        ),
        ActionSpec(
            "reply",
            "Send a customer-visible reply.",
            {"ticket_id": {"type": "string"}, "message": {"type": "string"}},
            ("ticket_id", "message"),
        ),
        ActionSpec(
            "resolve",
            "Resolve a ticket after required triage work.",
            {"ticket_id": {"type": "string"}},
            ("ticket_id",),
        ),
    )

    def initial_state(self, seed: int) -> dict[str, Any]:
        del seed
        return {
            "users": ["agent-lee", "on-call"],
            "tickets": {
                "TCK-100": {
                    "id": "TCK-100",
                    "customer": "Acme Corp",
                    "subject": "Production API unavailable",
                    "body": "All API requests have returned 503 for twelve minutes.",
                    "priority": "normal",
                    "status": "open",
                    "assignee": None,
                    "replies": [],
                },
                "TCK-101": {
                    "id": "TCK-101",
                    "customer": "Northstar Labs",
                    "subject": "How do I rotate an API key?",
                    "body": "Looking for the key rotation documentation.",
                    "priority": "low",
                    "status": "open",
                    "assignee": None,
                    "replies": [],
                },
            },
        }

    def actions(self) -> tuple[ActionSpec, ...]:
        return self.action_specs

    def _validate_params(self, action: str, params: dict[str, Any]) -> ActionSpec:
        spec = next((item for item in self.action_specs if item.name == action), None)
        if not spec:
            raise EnvironmentError(f"Unknown action: {action}")
        missing = [key for key in spec.required if key not in params]
        if missing:
            raise EnvironmentError(f"Missing required parameter(s): {', '.join(missing)}")
        unknown = set(params) - set(spec.parameters)
        if unknown:
            raise EnvironmentError(f"Unknown parameter(s): {', '.join(sorted(unknown))}")
        for key, value in params.items():
            schema = spec.parameters[key]
            if schema.get("type") == "string" and not isinstance(value, str):
                raise EnvironmentError(f"Parameter '{key}' must be a string")
            if "enum" in schema and value not in schema["enum"]:
                raise EnvironmentError(f"Parameter '{key}' must be one of {schema['enum']}")
        return spec

    def perform(self, state: dict[str, Any], action: str, params: dict[str, Any]) -> dict[str, Any]:
        self._validate_params(action, params)
        tickets = state["tickets"]
        if action == "list_tickets":
            items = list(tickets.values())
            if params.get("status"):
                items = [ticket for ticket in items if ticket["status"] == params["status"]]
            return {"tickets": deepcopy(items)}

        ticket_id = params["ticket_id"]
        if ticket_id not in tickets:
            raise EnvironmentError(f"Ticket not found: {ticket_id}")
        ticket = tickets[ticket_id]

        if action == "get_ticket":
            return {"ticket": deepcopy(ticket)}
        if action == "set_priority":
            ticket["priority"] = params["priority"]
            return {"ticket_id": ticket_id, "priority": ticket["priority"]}
        if action == "assign":
            if params["assignee"] not in state["users"]:
                raise EnvironmentError(f"Unknown assignee: {params['assignee']}")
            ticket["assignee"] = params["assignee"]
            return {"ticket_id": ticket_id, "assignee": ticket["assignee"]}
        if action == "reply":
            message = params["message"].strip()
            if not message:
                raise EnvironmentError("Reply message cannot be empty")
            ticket["replies"].append({"message": message, "visibility": "customer"})
            return {"ticket_id": ticket_id, "reply_count": len(ticket["replies"])}
        if action == "resolve":
            ticket["status"] = "resolved"
            return {"ticket_id": ticket_id, "status": "resolved"}
        raise AssertionError("unreachable")

    def validate(self, state: dict[str, Any]) -> ValidationResult:
        ticket = state["tickets"]["TCK-100"]
        reply_text = " ".join(reply["message"].lower() for reply in ticket["replies"])
        checks = (
            ValidationCheck("critical_priority", ticket["priority"] == "critical", "Ticket priority is critical."),
            ValidationCheck("on_call_assignment", ticket["assignee"] == "on-call", "Ticket is assigned to on-call."),
            ValidationCheck("outage_acknowledged", "outage" in reply_text, "Customer reply acknowledges the outage."),
            ValidationCheck("incident_mentioned", "incident" in reply_text, "Customer reply mentions an incident."),
            ValidationCheck("ticket_resolved", ticket["status"] == "resolved", "Ticket is resolved."),
        )
        passed_count = sum(check.passed for check in checks)
        return ValidationResult(passed_count == len(checks), passed_count / len(checks), checks)


ENVIRONMENTS = {SupportDeskEnvironment.id: SupportDeskEnvironment()}


def get_environment(environment_id: str) -> SupportDeskEnvironment:
    try:
        return ENVIRONMENTS[environment_id]
    except KeyError as exc:
        raise EnvironmentError(f"Unknown environment: {environment_id}") from exc

