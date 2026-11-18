"""WorldFoundry SDK transport contract for customer Supabase-backed resources."""
import pytest

from worldfoundry.cloud import CloudResourceManager, CloudWorldFoundry


class FakeTransport:
    def __init__(self):
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if "limit=" in path:
            return {"data": [{"id": "env1"}], "next_offset": None}
        return {"id": "env1", "version": 2}


def test_resource_templates_versions_archiving_and_pagination():
    transport = FakeTransport()
    templates = CloudResourceManager(transport, "templates")
    templates.create(project_id="p", name="Warehouse", config={"actions": {}})
    templates.configure("t1", expected_version=1, config={"actions": {"ship": {}}})
    templates.versions("t1")
    templates.version("t1", 1)
    templates.archive("t1", expected_version=2)
    templates.restore("t1", version=1, expected_version=3)
    templates.unarchive("t1", expected_version=4)
    items = list(templates.iter_all("p"))
    assert items == [{"id": "env1"}]
    assert transport.calls[0] == ("POST", "/v1/templates", {
        "project_id": "p", "name": "Warehouse", "config": {"actions": {}},
    })
    assert transport.calls[1] == ("PATCH", "/v1/templates/t1", {
        "expected_version": 1, "config": {"actions": {"ship": {}}},
    })
    assert transport.calls[2][1] == "/v1/templates/t1/versions?limit=50&offset=0"
    assert transport.calls[3][1] == "/v1/templates/t1/versions/1"
    assert transport.calls[4] == ("POST", "/v1/templates/t1/archive",
                                 {"expected_version": 2})
    assert transport.calls[5] == ("POST", "/v1/templates/t1/restore",
                                 {"version": 1, "expected_version": 3})
    assert transport.calls[7][1] == "/v1/templates?limit=100&offset=0&project_id=p"


def test_create_environment_from_reusable_template():
    transport = FakeTransport()
    envs = CloudResourceManager(transport, "environments")
    envs.from_template(project_id="p", name="Warehouse", template_id="t1",
                       template_version=2, overrides={"initial_state": {"stock": 5}})
    assert transport.calls == [("POST", "/v1/environments", {
        "project_id": "p", "name": "Warehouse", "template_id": "t1",
        "template_version": 2, "overrides": {"initial_state": {"stock": 5}},
    })]
    with pytest.raises(ValueError):
        CloudResourceManager(transport, "agents").from_template(
            project_id="p", name="n", template_id="t1")


def test_cloud_client_exposes_all_customer_resource_categories():
    wf = CloudWorldFoundry(api_key="wf_live_example")
    assert wf.templates.path == "templates"
    assert wf.environments.path == "environments"
    assert wf.scenarios.path == "scenarios"
    assert wf.workflows.path == "workflows"
    assert wf.applications.path == "applications"
    assert wf.tools.path == "tools"
    with pytest.raises(ValueError):
        wf.templates.list("p", limit=200)
