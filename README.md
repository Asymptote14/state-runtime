# State Runtime

State Runtime is a small deterministic runtime for validating and committing
LLM-proposed state transitions.

It does not generate stories, run NPCs, or call a model. A caller supplies
entities and a proposed transition; the runtime checks references, causes,
preconditions, and atomicity before changing state.

```text
current state + model proposal
            -> validate references and preconditions
            -> prepare a transaction without changing state
            -> commit every entity change or none
            -> append a causal event record
```

## Quick start

Requires Python 3.10 or newer and no runtime dependencies.

```powershell
python -m unittest discover -s tests -q
python examples/basic.py
```

## What is included

- Entity state with generic kinds and nested fields
- Required causal reason for every committed transition
- Entity reference and precondition validation
- Atomic multi-entity patches
- Duration-based world clock
- Append-only event records with replayable patches
- Reader-specific event visibility
- JSON-compatible snapshots for persistence or audit tools
- Explicit `prepare -> commit_prepared` transaction lifecycle
- Event replay and snapshot restoration

## Transaction lifecycle

`commit(proposal)` remains available as a compatibility shortcut. Code that
needs an explicit boundary can prepare first and commit later:

```python
prepared = runtime.prepare(proposal)  # validates; state is unchanged
event = runtime.commit_prepared(prepared)
```

Prepared events become invalid if another event is committed first. This
prevents a stale proposal from overwriting newer state.

## Replay

```python
snapshot = runtime.snapshot()
restored = StateRuntime.from_snapshot(snapshot)
replayed = StateRuntime.replay(initial_entities, runtime.events)
```

Replay applies recorded patches without calling an LLM or rerunning domain
logic, so the event history can be audited independently of its producer.

## What is deliberately absent

There is no built-in NPC schema, item system, physics engine, prompt format,
LLM client, scheduler, or narrative layer. Those belong in applications built
on top of this runtime.

The package is an early research extraction, not a mature workflow engine.

## License

MIT. See [LICENSE](LICENSE).
