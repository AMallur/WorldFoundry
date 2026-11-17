"""Custom Python templates, declarative scenarios, and connector snapshots."""
import json

from worldfoundry import (ActionSpec, ValidationCheck, ValidationResult,
                          WorldFoundry)
from worldfoundry.cli import main


class CounterEnvironment:
    id = "counter"
    name = "Counter"
    description = "Non-support workflow example"
    tasks = ("reach-target",)
    instruction = "Increase the counter to its target."

    def __init__(self, config):
        self.target = config["target"]

    def initial_state(self, seed):
        return {"value": seed % 3, "target": self.target}

    def actions(self):
        return (ActionSpec("inspect", "Read counter", {}),
                ActionSpec("increase", "Increment", {"amount": {"type": "number"}},
                           ("amount",)))

    def perform(self, state, action, params):
        if action == "inspect":
            return dict(state)
        if action == "increase":
            state["value"] += params["amount"]
            return dict(state)
        raise ValueError("Unknown action")

    def validate(self, state):
        passed = state["value"] == state["target"]
        return ValidationResult(passed, float(passed),
                                (ValidationCheck("target", passed, "Hit target"),))


def test_custom_python_template_config_snapshot_and_agent(tmp_path):
    wf = WorldFoundry.local(tmp_path)
    wf.environments.register_template("counter", CounterEnvironment)
    env = wf.environments.create(template="counter", config={"target": 7})

    def agent(task, tools):
        state = tools.inspect()
        tools.increase(amount=state["target"] - state["value"])
        tools.submit()

    registered = wf.agents.register(name="counter-policy", handler=agent)
    run = wf.training.create(agent=registered, environment=env, episodes=5, seed=4)
    assert run.success_rate == 1
    assert {wf.get(ep).seed % 3 for ep in run.episode_ids} == {0, 1, 2}
    assert {wf.get(ep).environment for ep in run.episode_ids} == {env.id}

    existing = wf.start(env.id, seed=1)
    wf.environments.configure(env.id, {"target": 9})
    wf.act(existing.id, "increase", amount=6)
    assert wf.submit(existing.id).passed
    assert wf.get(existing.id).environment_config["settings"]["target"] == 7
    fresh = wf.start(env.id, seed=1)
    assert fresh.state["target"] == 9


def test_declarative_scenario_generator_changes_state_and_injects_events(tmp_path):
    wf = WorldFoundry.local(tmp_path)
    env = wf.environments.create(template="declarative", config={
        "task": "dispatch",
        "instruction": "Ship order",
        "initial_state": {"order": {"status": "open", "quantity": 0, "notes": []}},
        "actions": {
            "inspect": {"operation": "read", "path": "order"},
            "ship": {"operation": "set", "path": "order.status", "value": "shipped"},
            "note": {"operation": "append", "path": "order.notes", "from_param": "message",
                     "parameters": {"message": {"type": "string"}}},
        },
    })

    def generator(seed, config):
        return {
            "instruction": "Ship batch " + str(seed),
            "state_overrides": {"order": {"quantity": seed + 1}},
            "events": [{"at_step": 1, "operation": "set", "path": "order.status",
                        "value": "held"}],
            "checks": [
                {"name": "shipped", "path": "order.status", "equals": "shipped"},
                {"name": "noted", "path": "order.notes", "equals": ["verified"]},
            ],
        }

    wf.scenarios.register_generator("dispatch_variation", generator)
    scene = wf.scenarios.create(name="Dispatch exceptions", generator="dispatch_variation")

    def agent(task, tools):
        assert "Ship batch" in task
        tools.inspect()
        tools.ship()
        tools.note(message="verified")
        tools.submit()

    registered = wf.agents.register(name="dispatch-policy", handler=agent)
    run = wf.training.create(agent=registered, environment=env, scenario=scene,
                             episodes=4, seed=2)
    assert run.success_rate == 1
    assert [wf.get(ep).state["order"]["quantity"] for ep in run.episode_ids] == [3, 4, 5, 6]
    for ep in run.episode_ids:
        events = wf.get(ep).trace
        assert any(event["type"] == "scenario.event" for event in events)
        assert [e["sequence"] for e in events] == list(range(len(events)))


def test_connector_snapshot_never_mutates_live_source(tmp_path):
    source = {"O1": {"status": "open"}}

    class Connector:
        calls = 0

        def snapshot(self):
            self.calls += 1
            return source.copy()

    wf = WorldFoundry.local(tmp_path)
    conn = Connector()
    wf.connectors.register("orders", conn)
    env = wf.environments.create(template="snapshot", config={
        "connector": "orders", "mount": "orders",
        "initial_state": {"orders": {}},
        "actions": {"ship": {"operation": "set", "path": "orders.O1.status",
                             "value": "shipped"}},
        "checks": [{"name": "shipped", "path": "orders.O1.status",
                    "equals": "shipped"}],
    })
    episode = wf.start(env.id)
    wf.act(episode.id, "ship")
    assert wf.submit(episode.id).passed
    assert conn.calls == 1
    assert source["O1"]["status"] == "open"


def test_cli_json_import_is_reopenable(tmp_path, capsys):
    config = {
        "name": "Warehouse", "template": "declarative",
        "config": {
            "initial_state": {"order": {"status": "open"}},
            "actions": {"ship": {"operation": "set", "path": "order.status",
                                 "value": "shipped"}},
            "checks": [{"name": "shipped", "path": "order.status",
                        "equals": "shipped"}],
        },
    }
    json_path = tmp_path / "warehouse.json"
    json_path.write_text(json.dumps(config))
    home = str(tmp_path / "state")
    assert main(["--home", home, "environments", "import", str(json_path)]) == 0
    resource = json.loads(capsys.readouterr().out)
    assert main(["--home", home, "episodes", "start", resource["id"]]) == 0
    episode = json.loads(capsys.readouterr().out)
    assert main(["--home", home, "episodes", "act", episode["id"], "ship"]) == 0
    capsys.readouterr()
    assert main(["--home", home, "episodes", "submit", episode["id"]]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True
