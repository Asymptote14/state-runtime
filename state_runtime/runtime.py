"""Deterministic validation and atomic commit for proposed state changes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from math import isclose, isfinite
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
    # Entities actually retrieved by the proposal producer.
    scope: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Proposal":
        """Parse a strict JSON-shaped proposal from an external producer."""
        if not isinstance(data, dict):
            raise ValidationError("proposal must be an object")
        allowed = {
            "cause", "changes", "preconditions", "duration",
            "visible_to", "metadata", "scope",
        }
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValidationError(f"unknown proposal fields: {', '.join(unknown)}")
        for field_name in ("cause", "changes"):
            if field_name not in data:
                raise ValidationError(f"missing proposal field: {field_name}")

        cause = data["cause"]
        if not isinstance(cause, str) or not cause.strip():
            raise ValidationError("proposal cause must be a non-empty string")

        raw_changes = data["changes"]
        if not isinstance(raw_changes, list) or not raw_changes:
            raise ValidationError("proposal changes must be a non-empty array")
        changes = []
        for index, raw_change in enumerate(raw_changes):
            prefix = f"changes[{index}]"
            if not isinstance(raw_change, dict):
                raise ValidationError(f"{prefix} must be an object")
            if set(raw_change) != {"entity_id", "patch"}:
                raise ValidationError(f"{prefix} must contain only entity_id and patch")
            entity_id = raw_change["entity_id"]
            patch = raw_change["patch"]
            if not isinstance(entity_id, str) or not entity_id:
                raise ValidationError(f"{prefix}.entity_id must be a non-empty string")
            if not isinstance(patch, dict) or not patch:
                raise ValidationError(f"{prefix}.patch must be a non-empty object")
            if any(not isinstance(path, str) for path in patch):
                raise ValidationError(f"{prefix}.patch keys must be strings")
            changes.append(Change(entity_id, deepcopy(patch)))

        raw_preconditions = data.get("preconditions", [])
        if not isinstance(raw_preconditions, list):
            raise ValidationError("proposal preconditions must be an array")
        preconditions = []
        for index, raw_condition in enumerate(raw_preconditions):
            prefix = f"preconditions[{index}]"
            if not isinstance(raw_condition, dict):
                raise ValidationError(f"{prefix} must be an object")
            allowed_condition = {"entity_id", "path", "equals", "exists"}
            if not set(raw_condition) <= allowed_condition:
                raise ValidationError(f"{prefix} contains unknown fields")
            if "entity_id" not in raw_condition or "path" not in raw_condition:
                raise ValidationError(f"{prefix} requires entity_id and path")
            entity_id = raw_condition["entity_id"]
            path = raw_condition["path"]
            if not isinstance(entity_id, str) or not entity_id:
                raise ValidationError(f"{prefix}.entity_id must be a non-empty string")
            if not isinstance(path, str) or not path:
                raise ValidationError(f"{prefix}.path must be a non-empty string")
            exists = raw_condition.get("exists", True)
            if not isinstance(exists, bool):
                raise ValidationError(f"{prefix}.exists must be boolean")
            if not exists and "equals" in raw_condition:
                raise ValidationError(f"{prefix}.equals is not allowed when exists is false")
            preconditions.append(Precondition(
                entity_id,
                path,
                deepcopy(raw_condition.get("equals")),
                exists,
            ))

        duration = data.get("duration", 0.0)
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise ValidationError("proposal duration must be a number")
        visible_to = _parse_string_array(data.get("visible_to", []), "visible_to")
        scope = _parse_string_array(data.get("scope", []), "scope")
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValidationError("proposal metadata must be an object")
        return cls(
            cause=cause,
            changes=tuple(changes),
            preconditions=tuple(preconditions),
            duration=float(duration),
            visible_to=tuple(visible_to),
            metadata=deepcopy(metadata),
            scope=tuple(scope),
        )


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
    scope: tuple[str, ...] = ()

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
            "scope": list(self.scope),
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
            scope=tuple(str(entity_id) for entity_id in data.get("scope", [])),
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


def _validate_path(path: str) -> None:
    if not isinstance(path, str) or not path.strip():
        raise ValidationError("state path is required")
    if path.startswith(".") or path.endswith(".") or ".." in path:
        raise ValidationError(f"invalid state path: {path!r}")


def _validate_scope(scope: tuple[str, ...]) -> None:
    if len(scope) != len(set(scope)):
        raise ValidationError("scope contains a duplicate entity")
    if any(not entity_id for entity_id in scope):
        raise ValidationError("scope contains an empty entity id")


def _parse_string_array(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError(f"proposal {field_name} must be an array")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValidationError(f"proposal {field_name} must contain non-empty strings")
    return value


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
        if not isfinite(proposal.duration) or proposal.duration < 0:
            raise ValidationError("duration cannot be negative")
        if not proposal.changes:
            raise ValidationError("proposal must change at least one entity")

        changed_ids = [change.entity_id for change in proposal.changes]
        if len(changed_ids) != len(set(changed_ids)):
            raise ValidationError("an entity may appear in only one change per event")
        for entity_id in changed_ids:
            if entity_id not in self.entities:
                raise ValidationError(f"unknown entity: {entity_id}")
        _validate_scope(proposal.scope)
        if proposal.scope:
            scope = set(proposal.scope)
            for entity_id in proposal.scope:
                if entity_id not in self.entities:
                    raise ValidationError(f"unknown scope entity: {entity_id}")
            outside = [entity_id for entity_id in changed_ids if entity_id not in scope]
            outside.extend(
                condition.entity_id
                for condition in proposal.preconditions
                if condition.entity_id not in scope
            )
            if outside:
                raise ValidationError(
                    f"proposal references entities outside scope: {', '.join(sorted(set(outside)))}"
                )
        for change in proposal.changes:
            if not change.patch:
                raise ValidationError("change patch cannot be empty")
            for path in change.patch:
                _validate_path(path)

        for condition in proposal.preconditions:
            entity = self.entities.get(condition.entity_id)
            if entity is None:
                raise ValidationError(f"unknown precondition entity: {condition.entity_id}")
            _validate_path(condition.path)
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

    @staticmethod
    def _validate_event_record(event: EventRecord) -> None:
        if event.event_id < 1:
            raise ValidationError("event id must be positive")
        if not event.cause.strip():
            raise ValidationError("event cause is required")
        if not isfinite(event.duration) or event.duration < 0:
            raise ValidationError("event duration cannot be negative")
        if not event.changes:
            raise ValidationError("event must contain at least one change")
        changed_ids = tuple(change.entity_id for change in event.changes)
        if len(changed_ids) != len(set(changed_ids)):
            raise ValidationError("event changes contain a duplicate entity")
        if tuple(event.entity_ids) != changed_ids:
            raise ValidationError("event entity_ids do not match its changes")
        _validate_scope(event.scope)
        if event.scope and not set(changed_ids) <= set(event.scope):
            raise ValidationError("event changes are outside scope")
        for change in event.changes:
            if not change.patch:
                raise ValidationError("event change patch cannot be empty")
            for path in change.patch:
                _validate_path(path)

    def prepare(self, proposal: Proposal) -> PreparedEvent:
        """Validate a proposal without mutating the runtime."""
        self._validate(proposal)
        resulting_entities = self._state_copy(self.entities)
        self._apply_changes(resulting_entities, proposal.changes)
        event = EventRecord(
            event_id=self._next_event_id(),
            clock=self.clock,
            duration=proposal.duration,
            cause=proposal.cause,
            entity_ids=tuple(change.entity_id for change in proposal.changes),
            changes=tuple(Change(c.entity_id, deepcopy(c.patch)) for c in proposal.changes),
            visible_to=tuple(proposal.visible_to),
            metadata=deepcopy(proposal.metadata),
            scope=tuple(proposal.scope),
        )
        return PreparedEvent(event, resulting_entities, self.clock, len(self.events))

    def _next_event_id(self) -> int:
        return max((event.event_id for event in self.events), default=0) + 1

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
            cls._validate_event_record(event)
            if event.scope and not set(event.scope) <= set(runtime.entities):
                raise ValidationError("event scope references an unknown entity")
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
        """Restore current state; event history is optional audit metadata.

        Unlike ``replay``, this method does not require a complete or
        contiguous event log. The entity snapshot and clock are authoritative,
        so a world can continue after history is omitted or truncated.
        """
        if not isinstance(snapshot, dict):
            raise ValidationError("snapshot must be an object")
        raw_entities = snapshot.get("entities", {})
        if not isinstance(raw_entities, dict):
            raise ValidationError("snapshot entities must be an object")
        entities = [
            Entity(str(data["id"]), str(data["kind"]), deepcopy(data.get("state", {})))
            for data in raw_entities.values()
        ]
        raw_events = snapshot.get("events", [])
        if not isinstance(raw_events, list):
            raise ValidationError("snapshot events must be an array")
        events = [EventRecord.from_dict(data) for data in raw_events]
        runtime = cls(entities)
        expected_clock = float(snapshot.get("clock", 0.0))
        if not isfinite(expected_clock) or expected_clock < 0:
            raise ValidationError("snapshot clock cannot be negative or non-finite")
        event_ids = set()
        for event in events:
            cls._validate_event_record(event)
            if event.event_id in event_ids:
                raise ValidationError("snapshot event history contains duplicate ids")
            event_ids.add(event.event_id)
        runtime.events = events
        runtime.clock = expected_clock
        return runtime

    def visible_events(self, reader_id: str) -> list[EventRecord]:
        """Return public events plus events explicitly visible to a reader."""
        return [
            event for event in self.events
            if not event.visible_to or reader_id in event.visible_to
        ]

    def snapshot(self, *, include_events: bool = True) -> dict[str, Any]:
        """Export current state, optionally including the audit event log."""
        snapshot = {
            "clock": self.clock,
            "entities": {
                entity_id: {
                    "id": entity.id,
                    "kind": entity.kind,
                    "state": deepcopy(entity.state),
                }
                for entity_id, entity in self.entities.items()
            },
        }
        if include_events:
            snapshot["events"] = [event.to_dict() for event in self.events]
        return snapshot
