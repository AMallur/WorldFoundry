import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from worldfoundry.engine import WorldFoundry
from worldfoundry.server import APIHandler


def request(base, path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        base + path,
        data=body,
        headers={"content-type": "application/json"} if body else {},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req) as response:
        return response.status, response.read(), response.headers["content-type"]


def test_rest_lifecycle(tmp_path):
    handler = type("TestHandler", (APIHandler,), {"client": WorldFoundry(tmp_path)})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, body, _ = request(base, "/health")
        assert status == 200
        assert json.loads(body) == {"status": "ok"}

        status, body, _ = request(base, "/v1/episodes", {"environment": "support-desk"})
        assert status == 201
        episode_id = json.loads(body)["id"]

        status, body, _ = request(
            base,
            f"/v1/episodes/{episode_id}/actions",
            {"action": "get_ticket", "parameters": {"ticket_id": "TCK-100"}},
        )
        assert status == 200
        assert json.loads(body)["observation"]["ticket"]["customer"] == "Acme Corp"

        status, body, content_type = request(base, f"/v1/episodes/{episode_id}/trace")
        assert status == 200
        assert content_type.startswith("application/x-ndjson")
        assert len(body.decode().splitlines()) == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_rest_rejects_bad_action(tmp_path):
    handler = type("TestHandler", (APIHandler,), {"client": WorldFoundry(tmp_path)})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        _, body, _ = request(base, "/v1/episodes", {"environment": "support-desk"})
        episode_id = json.loads(body)["id"]
        try:
            request(base, f"/v1/episodes/{episode_id}/actions", {"action": "destroy_all"})
            raise AssertionError("expected HTTP 400")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            assert json.loads(exc.read())["error"] == "invalid_request"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

