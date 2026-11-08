from worldfoundry import WorldFoundry
from worldfoundry.cloud import CloudWorldFoundry


def test_customer_key_uses_worldfoundry_gateway(monkeypatch):
    monkeypatch.delenv("WORLDFOUNDRY_API_URL", raising=False)
    wf = WorldFoundry(api_key="wf_live_example")
    assert isinstance(wf, CloudWorldFoundry)
    assert wf.projects.transport.base_url == "https://worldfoundry-api.vercel.app"
    assert wf.projects.transport.api_key == "wf_live_example"


def test_cloud_endpoint_can_be_overridden_for_development(monkeypatch):
    monkeypatch.setenv("WORLDFOUNDRY_API_URL", "http://127.0.0.1:8787")
    wf = WorldFoundry(api_key="wf_live_example")
    assert wf.projects.transport.base_url == "http://127.0.0.1:8787"
