"""WorldFoundry public SDK client."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .engine import EpisodeEngine
from .platform import AgentManager, EnvironmentManager, Registry, ResourceManager, TrainingManager

if TYPE_CHECKING:
    from .cloud import CloudWorldFoundry


class WorldFoundry(EpisodeEngine):
    def __new__(cls, home: str | Path | None = None, *, api_key: str | None = None,
                base_url: str | None = None):
        if api_key or base_url:
            if not api_key or not base_url or home is not None:
                raise ValueError("Cloud mode needs both api_key and base_url, without a local home")
            from .cloud import CloudWorldFoundry
            return CloudWorldFoundry(base_url=base_url, api_key=api_key)
        return super().__new__(cls)

    def __init__(self, home: str | Path | None = None, *, api_key: str | None = None,
                 base_url: str | None = None):
        super().__init__(home)
        registry = Registry(self.store.root)
        self.projects = ResourceManager(registry, "project")
        self.environments = EnvironmentManager(registry, "environment")
        self.agents = AgentManager(registry)
        self.scenarios = ResourceManager(registry, "scenario")
        self.datasets = ResourceManager(registry, "dataset")
        self.policies = ResourceManager(registry, "policy")
        self.feedback = ResourceManager(registry, "feedback")
        self.training = TrainingManager(self, self.agents, registry)

    @classmethod
    def local(cls, data_dir: str | Path | None = None) -> WorldFoundry:
        return cls(data_dir)

    @classmethod
    def cloud(cls, *, base_url: str, api_key: str) -> CloudWorldFoundry:
        from .cloud import CloudWorldFoundry
        return CloudWorldFoundry(base_url=base_url, api_key=api_key)

