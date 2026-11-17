"""Extension registration is explicit and works across local CLI/REST processes."""
import json
import threading
from http.server import ThreadingHTTPServer

from worldfoundry import WorldFoundry
from worldfoundry.cli import main
from worldfoundry.server import APIHandler


def test_trusted_python_plugin_reloaded_by_second_process(tmp_path, monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(tmp_path))
    plugin = tmp_path / "warehouse_plugin.py"
    plugin.write_text(
        "from worldfoundry import DeclarativeEnvironment\n"
        "def register(wf):\n"
        "    wf.environments.register_template('warehouse', DeclarativeEnvironment)\n"
    )
    home = str(tmp_path / "data")
    wf = WorldFoundry.local(home, plugins=["warehouse_plugin"])
    env = wf.environments.create(template="warehouse", config={
        "initial_state": {"stock": {"count": 0}},
        "actions": {"fill": {"operation": "increment", "path": "stock.count",
                             "value": 1}},
        "checks": [{"name": "stock", "path": "stock.count", "equals": 1}],
    })
    episode = wf.start(env.id)
    reopened = WorldFoundry.local(home, plugins=["warehouse_plugin"])
    reopened.act(episode.id, "fill")
    assert reopened.submit(episode.id).passed
    assert main(["--home", home, "--plugin", "warehouse_plugin",
                 "environments", "list"]) == 0
    assert "warehouse" in capsys.readouterr().out


def test_agent_object_adapter_and_injected_failure_rollback(tmp_path):
    wf = WorldFoundry.local(tmp_path)
    env = wf.environments.create(template="declarative", config={
        "initial_state": {"stock": {"count": 0}},
        "actions": {"fill": {"operation": "increment", "path": "stock.count",
                             "value": 1}},
        "checks": [{"name": "stock", "path": "stock.count", "equals": 1}],
    })

    class Adapter:
        def run(self, instruction, tools):
            tools.fill()
            tools.submit()

    agent = wf.agents.register(name="custom-adapter", adapter=Adapter())
    assert wf.training.create(agent=agent, environment=env).success_rate == 1
    episode = wf.start(env.id, scenario={
        "events": [{"at_step": 1, "operation": "set",
                    "path": "unknown.nonexistent", "value": True}],
    })
    from worldfoundry.environments import EnvironmentError

    try:
        wf.act(episode.id, "fill")
        raise AssertionError("Expected event failure")
    except EnvironmentError:
        pass
    assert wf.get(episode.id).state["stock"]["count"] == 0
    assert wf.get(episode.id).trace[-1]["type"] == "action.failed"


def test_local_rest_can_create_custom_environment(tmp_path):
    from urllib.request import Request, urlopen

    wf = WorldFoundry.local(tmp_path)
    handler = type("CustomAPIHandler", (APIHandler,), {"client": wf})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = f"http://127.0.0.1:{server.server_port}"

    def post(path, data):
        request = Request(root + path, data=json.dumps(data).encode(),
                          headers={"content-type": "application/json"}, method="POST")
        with urlopen(request, timeout=5) as response:
            return response.status, json.load(response)

    try:
        status, resource = post("/v1/environments", {
            "template": "declarative",
            "config": {
                "initial_state": {"order": {"status": "open"}},
                "actions": {"ship": {"operation": "set", "path": "order.status",
                                     "value": "shipped"}},
                "checks": [{"name": "done", "path": "order.status", "equals": "shipped"}],
            },
        })
        assert status == 201
        status, episode = post("/v1/episodes", {"environment": resource["id"]})
        assert status == 201
        post("/v1/episodes/" + episode["id"] + "/actions", {"action": "ship"})
        status, report = post("/v1/episodes/" + episode["id"] + "/submit", {})
        assert status == 200 and report["score"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
