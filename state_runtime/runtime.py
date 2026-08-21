"""Deterministic validation and atomic commit for proposed state changes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


class ValidationError(ValueError):
    """Raised when a proposal cannot be committed."""


@dataclass
class Entity:
    id: str
    kind: str
    state: dict[str, Any] = field(default_factory=dict)

    def clone(self) -> "Entity":
        return Entity(self.id, self.kind, deepcopy(self.state))


@dataclass(frozen=True)
class Precondition:
    entity_id: str
    path: str
    equals: Any = None
    exists: bool = True


@dataclass(frozen=True)
class Change:
    entity_id: str
    patch: dict[str, Any]


@dataclass(frozen=True)
class Proposal:
    cause: str
    changes: tuple[Change, ...]
    preconditions: tuple[Precondition, ...] = ()
    duration: float = 0.0
    visible_to: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EventRecord:
    event_id: int
    clock: float
    duration: float
    cause: str
    entity_ids: tuple[str, ...]
    changes: tuple[Change, ...]
    visible_to: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


def _read_path(state: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = state
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _write_path(state: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = state
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = deepcopy(value)


class StateRuntime:
    """Owns entity state and commits validated proposals atomically."""

    def __init__(self, entities: list[Entity] | None = None) -> None:
        self.entities: dict[str, Entity] = {}
        for entity in entities or []:
            self.add_entity(entity)
        self.clock = 0.0
        self.events: list[EventRecord] = []

    def add_entity(self, entity: Entity) -> None:
        if not entity.id or entity.id in self.entities:
            raise ValidationError(f"duplicate or empty entity id: {entity.id!r}")
        self.entities[entity.id] = entity.clone()

    def _validate(self, proposal: Proposal) -> None:
        if not proposal.cause.strip():
            raise ValidationError("cause is required")
        if proposal.duration < 0:
            raise ValidationError("duration cannot be negative")
        if not proposal.changes:
            raise ValidationError("proposal must change at least one entity")

        changed_ids = [change.entity_id for change in proposal.changes]
        if len(changed_ids) != len(set(changed_ids)):
            raise ValidationError("an entity may appear in only one change per event")
        for entity_id in changed_ids:
            if entity_id not in self.entities:
                raise ValidationError(f"unknown entity: {entity_id}")

        for condition in proposal.preconditions:
            entity = self.entities.get(condition.entity_id)
            if entity is None:
                raise ValidationError(f"unknown precondition entity: {condition.entity_id}")
            exists, actual = _read_path(entity.state, condition.path)
            if exists != condition.exists:
                raise ValidationError(
                    f"precondition failed: {condition.entity_id}.{condition.path} "
                    f"exists={exists}, expected={condition.exists}"
                )
            if condition.exists and actual != condition.equals:
                raise ValidationError(
                    f"precondition failed: {condition.entity_id}.{condition.path} "
                    f"is {actual!r}, expected {condition.equals!r}"
                )

    def commit(self, proposal: Proposal) -> EventRecord:
        """Validate every change, then apply all changes or none."""
        self._validate(proposal)
        for change in proposal.changes:
            entity = self.entities[change.entity_id]
            for path, value in change.patch.items():
                _write_path(entity.state, path, value)

        event = EventRecord(
            event_id=len(self.events) + 1,
            clock=self.clock,
            duration=proposal.duration,
            cause=proposal.cause,
            entity_ids=tuple(change.entity_id for change in proposal.changes),
            changes=tuple(Change(c.entity_id, deepcopy(c.patch)) for c in proposal.changes),
            visible_to=tuple(proposal.visible_to),
            metadata=deepcopy(proposal.metadata),
        )
        self.events.append(event)
        self.clock += proposal.duration
        return event

    def visible_events(self, reader_id: str) -> list[EventRecord]:
        """Return public events plus events explicitly visible to a reader."""
        return [
            event for event in self.events
            if not event.visible_to or reader_id in event.visible_to
        ]

    def snapshot(self) -> dict[str, Any]:
        return {
            "clock": self.clock,
            "entities": {
                entity_id: {
                    "id": entity.id,
                    "kind": entity.kind,
                    "state": deepcopy(entity.state),
                }
                for entity_id, entity in self.entities.items()
            },
            "events": [
                {
                    "event_id": event.event_id,
                    "clock": event.clock,
                    "duration": event.duration,
                    "cause": event.cause,
                    "entity_ids": list(event.entity_ids),
                    "changes": [
                        {"entity_id": change.entity_id, "patch": deepcopy(change.patch)}
                        for change in event.changes
                    ],
                    "visible_to": list(event.visible_to),
                    "metadata": deepcopy(event.metadata),
                }
                for event in self.events
            ],
        }
