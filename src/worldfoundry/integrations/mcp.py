"""Expose an existing *local* WorldFoundry episode to any MCP-compatible agent.

The MCP process runs with the permissions of the developer who starts it.
It never writes to customer systems or opens a public network endpoint.
Install with: pip install "worldfoundry[mcp]"
"""
from __future__ import annotations

import argparse
from typing import Any

from ..client import WorldFoundry


def create_server(client: WorldFoundry, episode_id: str) -> Any:
    """Return a FastMCP stdio server bound to a single persistent episode."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError('MCP support requires pip install "worldfoundry[mcp]"') from exc
    client.get(episode_id)  # Reject missing episodes when binding, not during first tool call.
    server = FastMCP("worldfoundry")

    @server.tool()
    def worldfoundry_actions() -> list[str]:
        """List the available actions in the current simulation."""
        return client.available_actions(episode_id)

    @server.tool()
    def worldfoundry_action(action: str,
                            parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform a simulated action; never call a live customer application."""
        return client.act(episode_id, action, **(parameters or {})).to_dict()

    @server.tool()
    def worldfoundry_submit() -> dict[str, Any]:
        """Finish and grade this simulation against its checks."""
        return client.submit(episode_id).to_dict()

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Bind one WorldFoundry episode to an MCP server")
    parser.add_argument("--episode", required=True, help="An existing local episode ID")
    parser.add_argument("--home", help="Local WorldFoundry state directory")
    args = parser.parse_args(argv)
    server = create_server(WorldFoundry.local(args.home), args.episode)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
