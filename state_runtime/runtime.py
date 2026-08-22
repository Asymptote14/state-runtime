"""Deterministic validation and atomic commit for proposed state changes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from math import isclose
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "clock": self.clock,
            "duration": self.duration,
            "cause": self.cause,
            "entity_ids": list(self.entity_ids),
            "changes": [
                {"entity_id": change.entity_id, "patch": deepcopy(change.patch)}
                for change in self.changes
            ],
            "visible_to": list(self.visible_to),
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventRecord":
        return cls(
            event_id=int(data["event_id"]),
            clock=float(data["clock"]),
            duration=float(data["duration"]),
            cause=str(data["cause"]),
            entity_ids=tuple(str(entity_id) for entity_id in data["entity_ids"]),
            changes=tuple(
                Change(str(change["entity_id"]), deepcopy(change["patch"]))
                for change in data["changes"]
            ),
            visible_to=tuple(str(reader) for reader in data.get("visible_to", [])),
            metadata=deepcopy(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class PreparedEvent:
    """A validated event with the state it would produce."""

    event: EventRecord
    resulting_entities: dict[str, Entity]
    base_clock: float
    base_event_count: int


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


def _same_clock(left: float, right: float) -> bool:
    return isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


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

    @staticmethod
    def _state_copy(entities: dict[str, Entity]) -> dict[str, Entity]:
        return {entity_id: entity.clone() for entity_id, entity in entities.items()}

    @staticmethod
    def _apply_changes(entities: dict[str, Entity], changes: tuple[Change, ...]) -> None:
        for change in changes:
            entity = entities.get(change.entity_id)
            if entity is None:
                raise ValidationError(f"unknown entity: {change.entity_id}")
            for path, value in change.patch.items():
                _write_path(entity.state, path, value)

    def prepare(self, proposal: Proposal) -> PreparedEvent:
        """Validate a proposal without mutating the runtime."""
        self._validate(proposal)
        resulting_entities = self._state_copy(self.entities)
        self._apply_changes(resulting_entities, proposal.changes)
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
        return PreparedEvent(event, resulting_entities, self.clock, len(self.events))

    def commit_prepared(self, prepared: PreparedEvent) -> EventRecord:
        """Commit a prepared event if the runtime has not changed meanwhile."""
        if prepared.base_clock != self.clock or prepared.base_event_count != len(self.events):
            raise ValidationError("prepared event is stale")
        self.entities = self._state_copy(prepared.resulting_entities)
        self.events.append(prepared.event)
        self.clock += prepared.event.duration
        return prepared.event

    def commit(self, proposal: Proposal) -> EventRecord:
        """Compatibility shortcut for ``commit_prepared(prepare(proposal))``."""
        return self.commit_prepared(self.prepare(proposal))

    @classmethod
    def replay(cls, initial_entities: list[Entity], events: list[EventRecord]) -> "StateRuntime":
        """Rebuild a runtime from initial entities and append-only event records."""
        runtime = cls(initial_entities)
        for event in events:
            if not _same_clock(event.clock, runtime.clock):
                raise ValidationError(
                    f"event {event.event_id} starts at {event.clock}, "
                    f"expected {runtime.clock}"
                )
            if event.event_id != len(runtime.events) + 1:
                raise ValidationError(f"unexpected event id: {event.event_id}")
            if event.duration < 0:
                raise ValidationError("event duration cannot be negative")
            if not event.cause.strip():
                raise ValidationError("event cause is required")
            runtime._apply_changes(runtime.entities, event.changes)
            runtime.events.append(event)
            runtime.clock += event.duration
        return runtime

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "StateRuntime":
        """Restore a complete snapshot, including its event history."""
        entities = [
            Entity(str(data["id"]), str(data["kind"]), deepcopy(data.get("state", {})))
            for data in snapshot.get("entities", {}).values()
        ]
        events = [EventRecord.from_dict(data) for data in snapshot.get("events", [])]
        runtime = cls(entities)
        expected_clock = float(snapshot.get("clock", 0.0))
        expected_event_id = 1
        expected_clock_from_events = 0.0
        for event in events:
            if (
                event.event_id != expected_event_id
                or not _same_clock(event.clock, expected_clock_from_events)
            ):
                raise ValidationError("snapshot event history is not contiguous")
            if event.duration < 0 or not event.cause.strip():
                raise ValidationError("snapshot contains an invalid event")
            expected_event_id += 1
            expected_clock_from_events += event.duration
        if not _same_clock(expected_clock_from_events, expected_clock):
            raise ValidationError("snapshot clock does not match event history")
        runtime.events = events
        runtime.clock = expected_clock
        return runtime

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
            "events": [event.to_dict() for event in self.events],
        }
