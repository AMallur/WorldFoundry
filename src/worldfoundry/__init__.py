"""WorldFoundry local training-experience SDK."""

from .client import WorldFoundry
from .declarative import DeclarativeEnvironment
from .extensibility import ConnectorRegistry, EnvironmentPlugin, TemplateRegistry
from .models import ActionSpec, Episode, StepResult, ValidationCheck, ValidationResult

__all__ = [
    "ActionSpec", "ConnectorRegistry", "DeclarativeEnvironment", "EnvironmentPlugin",
    "Episode", "StepResult", "TemplateRegistry", "ValidationCheck", "ValidationResult",
    "WorldFoundry",
]
__version__ = "0.6.0"

