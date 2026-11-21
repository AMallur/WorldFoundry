"""Optional local runner for Meta Agents Research Environments (ARE).

This launches a separately installed ARE scenario with its documented CLI.
It does not claim to mirror WorldFoundry state into ARE universes or apps.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True)
class ARERunResult:
    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict:
        return asdict(self)


class MetaARERunner:
    """Run a local ARE research scenario through its official are-run interface."""

    def __init__(self, *, use_uvx: bool = False, timeout_seconds: int = 180):
        if not 1 <= timeout_seconds <= 3600:
            raise ValueError("timeout_seconds must be 1..3600")
        self.use_uvx = use_uvx
        self.timeout_seconds = timeout_seconds

    def run(self, scenario: str, *, agent: str = "default",
            provider: str = "mock", model: str | None = None) -> ARERunResult:
        for name, value in {"scenario": scenario, "agent": agent,
                            "provider": provider}.items():
            if not isinstance(value, str) or not _NAME.fullmatch(value):
                raise ValueError(f"Unsafe {name} name")
        if model is not None and (not isinstance(model, str) or
                                  not _NAME.fullmatch(model)):
            raise ValueError("Unsafe model identifier")
        command = (["uvx", "--from", "meta-agents-research-environments", "are-run"]
                   if self.use_uvx else ["are-run"])
        if shutil.which(command[0]) is None:
            raise RuntimeError(f"{command[0]} is not installed")
        command += ["-s", scenario, "-a", agent, "--provider", provider]
        if model:
            command += ["--model", model]
        try:
            result = subprocess.run(command, check=False, capture_output=True,
                                    text=True, timeout=self.timeout_seconds, shell=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("ARE simulation exceeded its configured timeout") from exc
        return ARERunResult(tuple(command), result.returncode,
                            result.stdout[-65536:], result.stderr[-65536:])
