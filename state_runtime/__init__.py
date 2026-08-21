"""A small deterministic runtime for validating state transitions."""

from .runtime import (
    Change,
    Entity,
    EventRecord,
    Precondition,
    Proposal,
    StateRuntime,
    ValidationError,
)

__all__ = [
    "Change",
    "Entity",
    "EventRecord",
    "Precondition",
    "Proposal",
    "StateRuntime",
    "ValidationError",
]

__version__ = "0.1.0"
