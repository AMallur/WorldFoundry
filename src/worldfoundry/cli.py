from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .client import WorldFoundry
from .environments import EnvironmentError
from .server import serve
from .store import EpisodeNotFound


def _print(data: Any) -> None:
    print(json.dumps(data, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="worldfoundry", description="Local training environments for AI agents")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--home", help="State directory (default: $WORLDFOUNDRY_HOME or ~/.worldfoundry)")
    parser.add_argument("--plugin", action="append", default=[],
                        help="Import a trusted local Python plugin module with register(wf). "
                             "Repeat for more modules.")
    commands = parser.add_subparsers(dest="command", required=True)

    environments = commands.add_parser("environments", help="Discover environments")
    env_commands = environments.add_subparsers(dest="subcommand", required=True)
    env_commands.add_parser("list")
    env_import = env_commands.add_parser("import", help="Register a JSON template configuration")
    env_import.add_argument("file")

    episodes = commands.add_parser("episodes", help="Run episodes")
    episode_commands = episodes.add_subparsers(dest="subcommand", required=True)
    start = episode_commands.add_parser("start")
    start.add_argument("environment")
    start.add_argument("--task", default=None)
    start.add_argument("--seed", type=int, default=0)
    start.add_argument("--scenario-file", help="Optional JSON scenario configuration")
    episode_commands.add_parser("list")
    inspect = episode_commands.add_parser("inspect")
    inspect.add_argument("episode_id")
    act = episode_commands.add_parser("act")
    act.add_argument("episode_id")
    act.add_argument("action")
    act.add_argument("--params", default="{}", help="JSON object of action parameters")
    submit = episode_commands.add_parser("submit")
    submit.add_argument("episode_id")

    traces = commands.add_parser("traces", help="Export episode traces")
    trace_commands = traces.add_subparsers(dest="subcommand", required=True)
    export = trace_commands.add_parser("export")
    export.add_argument("episode_id")
    export.add_argument("--output", "-o", required=True)

    server = commands.add_parser("serve", help="Run the local REST API")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8787)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    local_modules = [module.strip() for module in os.getenv("WORLDFOUNDRY_PLUGINS", "").split(",")
                     if module.strip()]
    modules = [*local_modules, *args.plugin]
    if args.command == "serve":
        serve(args.host, args.port, args.home, plugins=modules)
        return 0
    client = WorldFoundry.local(args.home, plugins=modules)
    try:
        if args.command == "environments" and args.subcommand == "list":
            _print({"data": client.environment_catalog()})
        elif args.command == "environments" and args.subcommand == "import":
            from dataclasses import asdict

            _print(asdict(client.environments.from_file(args.file)))
        elif args.command == "episodes" and args.subcommand == "start":
            scenario = (json.loads(Path(args.scenario_file).read_text(encoding="utf-8"))
                        if args.scenario_file else None)
            _print(client.start(args.environment, args.task, args.seed,
                                scenario=scenario).to_dict())
        elif args.command == "episodes" and args.subcommand == "list":
            _print({"data": [ep.to_dict(include_state=False) for ep in client.list_episodes()]})
        elif args.command == "episodes" and args.subcommand == "inspect":
            _print(client.get(args.episode_id).to_dict())
        elif args.command == "episodes" and args.subcommand == "act":
            params = json.loads(args.params)
            if not isinstance(params, dict):
                raise ValueError("--params must be a JSON object")
            _print(client.act(args.episode_id, args.action, **params).to_dict())
        elif args.command == "episodes" and args.subcommand == "submit":
            _print(client.submit(args.episode_id).to_dict())
        elif args.command == "traces":
            path = client.export_trace(args.episode_id, Path(args.output))
            _print({"episode_id": args.episode_id, "output": str(path), "format": "jsonl"})
        return 0
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in --params: {exc}", file=sys.stderr)
    except (ValueError, EnvironmentError) as exc:
        print(f"error: {exc}", file=sys.stderr)
    except EpisodeNotFound as exc:
        print(f"error: episode not found: {exc.args[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

