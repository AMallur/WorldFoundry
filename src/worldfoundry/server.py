from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .client import WorldFoundry
from .environments import EnvironmentError
from .store import EpisodeNotFound


def _json_bytes(data: Any) -> bytes:
    return (json.dumps(data, indent=2) + "\n").encode()


class APIHandler(BaseHTTPRequestHandler):
    server_version = "WorldFoundry/0.1"
    client: WorldFoundry

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _send(self, status: int, data: Any, content_type: str = "application/json") -> None:
        body = _json_bytes(data) if content_type == "application/json" else data.encode()
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise TypeError("JSON body must be an object")
        return data

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/health":
                self._send(200, {"status": "ok"})
                return
            if path == "/v1/environments":
                self._send(200, {"data": self.client.environment_catalog()})
                return
            if path == "/v1/episodes":
                data = [ep.to_dict(include_state=False) for ep in self.client.list_episodes()]
                self._send(200, {"data": data})
                return
            match = re.fullmatch(r"/v1/episodes/([^/]+)", path)
            if match:
                self._send(200, self.client.get(match.group(1)).to_dict())
                return
            match = re.fullmatch(r"/v1/episodes/([^/]+)/trace", path)
            if match:
                episode = self.client.get(match.group(1))
                text = "\n".join(json.dumps(event, sort_keys=True) for event in episode.trace) + "\n"
                self._send(200, text, "application/x-ndjson")
                return
            self._send(404, {"error": "not_found", "message": f"No route for GET {path}"})
        except EpisodeNotFound as exc:
            self._send(404, {"error": "episode_not_found", "message": str(exc.args[0])})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/v1/episodes":
                episode = self.client.start(
                    body.get("environment", "support-desk"),
                    body.get("task", "incident-triage"),
                    int(body.get("seed", 0)),
                )
                self._send(201, episode.to_dict())
                return
            match = re.fullmatch(r"/v1/episodes/([^/]+)/actions", path)
            if match:
                action = body.pop("action", None)
                if not action:
                    raise ValueError("Body requires an 'action' field")
                params = body.pop("parameters", body)
                self._send(200, self.client.act(match.group(1), action, **params).to_dict())
                return
            match = re.fullmatch(r"/v1/episodes/([^/]+)/submit", path)
            if match:
                self._send(200, self.client.submit(match.group(1)).to_dict())
                return
            self._send(404, {"error": "not_found", "message": f"No route for POST {path}"})
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid_json", "message": "Request body is not valid JSON"})
        except (TypeError, ValueError, EnvironmentError) as exc:
            self._send(400, {"error": "invalid_request", "message": str(exc)})
        except EpisodeNotFound as exc:
            self._send(404, {"error": "episode_not_found", "message": str(exc.args[0])})


def serve(host: str = "127.0.0.1", port: int = 8787, home: str | None = None) -> None:
    handler = type("BoundAPIHandler", (APIHandler,), {"client": WorldFoundry(home)})
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"WorldFoundry API listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

