# State Runtime

An LLM can suggest a state transition, but it should not directly mutate
application state. This repository is a small, dependency-free Python
prototype for putting a deterministic boundary between those two steps.

The caller supplies the current entities and a proposed transition. The
runtime checks references, causes, preconditions, and atomicity before
changing anything. Invalid or stale proposals are rejected without partial
writes.

This is an early research prototype, not a production workflow engine,
physics engine, or agent framework.

```text
current state + model proposal
            -> validate references and preconditions
            -> prepare a transaction without changing state
            -> commit every entity change or none
            -> append a causal event record
```

## Smallest useful example

```python
candidate = Proposal.from_dict(model_output)
prepared = runtime.prepare(candidate)  # validates; state is unchanged
event = runtime.commit_prepared(prepared)
```

The model produces data shaped like a `Proposal`. It does not receive a
reference to `runtime.entities` and it does not call a state mutation method.
The application decides what entities to expose and what proposal to submit.

For a complete item-transfer example, run:

```powershell
python examples/transfer.py
```

The example prints:

```text
prepared event=1; state unchanged=True
committed event=1; holder=player
rejected stale proposal: precondition failed: item:letter.holder is 'player', expected 'person:zhou'
state unchanged after rejection=True
replay matches current state=True
```

The important behavior is the rejection: the proposal has the right shape,
but its precondition no longer matches the current state, so it is not
committed.

## Quick start

Requires Python 3.10 or newer and no runtime dependencies.

```powershell
python -m unittest discover -s tests -q
python examples/basic.py
python examples/transfer.py
python examples/scoped_transfer.py
python examples/mock_llm.py
```

## What is included

- Entity state with generic kinds and nested fields
- Required causal reason for every committed transition
- Entity reference and precondition validation
- Atomic multi-entity patches
- Duration-based world clock
- Append-only event records with replayable patches
- Reader-specific event visibility
- Optional retrieval scope that prevents out-of-scope reads and writes
- JSON-compatible snapshots for persistence or audit tools
- Current-state snapshots that can resume without event history
- Explicit `prepare -> commit_prepared` transaction lifecycle
- Event replay and snapshot restoration
- Strict parsing of external JSON-shaped proposals

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

`replay()` is intentionally strict: it expects a complete contiguous event
sequence. It is an audit operation, not a prerequisite for running the world.

To persist only the current world state, omit the audit log:

```python
state_snapshot = runtime.snapshot(include_events=False)
resumed = StateRuntime.from_snapshot(state_snapshot)
```

`from_snapshot()` treats `entities` and `clock` as authoritative. It can also
resume from a snapshot whose event history is missing or truncated. Existing
events are retained as optional audit records, and new event IDs continue after
the largest retained ID.

## Retrieval scope

An adapter can declare which entities were actually retrieved for a proposal.
When `scope` is present, every precondition and change must refer to an entity
inside that scope. The scope is copied into the committed event for audit:

```python
proposal = Proposal(
    cause="Zhou transfers the letter",
    preconditions=(Precondition("item:letter", "holder", "person:zhou"),),
    changes=(Change("item:letter", {"holder": "player"}),),
    scope=("item:letter", "person:zhou", "player"),
)
runtime.commit(proposal)
```

An omitted scope preserves the compatibility behavior of the early prototype;
the runtime does not pretend to know what an external retriever supplied.

Run `python examples/scoped_transfer.py` for a complete multi-entity example:
the person, item, place, and player are committed together, while a proposal
that writes outside its declared retrieval scope is rejected atomically.

Run `python examples/transfer.py` for the smallest end-to-end transfer proof:
JSON-shaped proposal parsing, side-effect-free `prepare()`, one atomic commit,
stale proposal rejection with unchanged state, and event replay.

## Model boundary

External model output can be parsed with `Proposal.from_dict()`. Parsing checks
the shape and types of the proposal; the runtime then checks entity references,
preconditions, and retrieval scope:

```python
candidate = Proposal.from_dict(model_json)
event = runtime.commit(candidate)
```

Malformed model output fails during parsing. A well-shaped but stale or
out-of-scope proposal fails during runtime validation, without partial writes.
Run `python examples/mock_llm.py` to see both rejection layers and a successful
commit. The example uses a deterministic function instead of a network model.

## What is deliberately absent

There is no built-in NPC schema, item system, physics engine, prompt format,
LLM client, scheduler, or narrative layer. Those belong in applications built
on top of this runtime.

The package is an early research extraction, not a mature workflow engine.

## License

MIT. See [LICENSE](LICENSE).
