# State Runtime

State Runtime is a small deterministic runtime for validating and committing
LLM-proposed state transitions.

It does not generate stories, run NPCs, or call a model. A caller supplies
entities and a proposed transition; the runtime checks references, causes,
preconditions, and atomicity before changing state.

```text
current state + model proposal
            -> validate references and preconditions
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

## What is deliberately absent

There is no built-in NPC schema, item system, physics engine, prompt format,
LLM client, scheduler, or narrative layer. Those belong in applications built
on top of this runtime.

The package is an early research extraction, not a mature workflow engine.

## License

MIT. See [LICENSE](LICENSE).
