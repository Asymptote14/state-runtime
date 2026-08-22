"""A small deterministic runtime for validating state transitions."""

from .runtime import (
    Change,
    Entity,
    EventRecord,
    PreparedEvent,
    Precondition,
    Proposal,
    StateRuntime,
    ValidationError,
)

__all__ = [
    "Change",
    "Entity",
    "EventRecord",
    "PreparedEvent",
    "Precondition",
    "Proposal",
    "StateRuntime",
    "ValidationError",
]

__version__ = "0.2.0"
