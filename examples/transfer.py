"""End-to-end generic item transfer: parse, prepare, commit, reject, replay."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from state_runtime import Entity, EventRecord, Proposal, StateRuntime, ValidationError


def build_runtime() -> StateRuntime:
    return StateRuntime([
        Entity("person:zhou", "person", {"location": "place:station"}),
        Entity("item:letter", "item", {
            "holder": "person:zhou",
            "location": "place:station",
        }),
        Entity("place:station", "place", {"mark": "sealed letter on desk"}),
        Entity("player", "player", {"location": "place:station"}),
    ])


def transfer_json(expected_holder: str) -> dict:
    """The shape a model or another application could produce."""
    return {
        "cause": "person:zhou hands the letter to the player",
        "preconditions": [{
            "entity_id": "item:letter",
            "path": "holder",
            "equals": expected_holder,
        }],
        "changes": [
            {"entity_id": "item:letter", "patch": {
                "holder": "player", "location": None,
            }},
            {"entity_id": "place:station", "patch": {
                "mark": "an empty space on the desk",
            }},
        ],
        "scope": ["item:letter", "place:station", "player"],
        "duration": 0.25,
        "visible_to": ["player"],
    }


def main() -> None:
    runtime = build_runtime()
    initial = [entity.clone() for entity in runtime.entities.values()]

    proposal = Proposal.from_dict(transfer_json("person:zhou"))
    prepared = runtime.prepare(proposal)
    print(f"prepared event={prepared.event.event_id}; state unchanged={not runtime.events}")
    committed = runtime.commit_prepared(prepared)
    print(f"committed event={committed.event_id}; holder="
          f"{runtime.entities['item:letter'].state['holder']}")

    before_rejection = runtime.snapshot()
    try:
        runtime.commit(Proposal.from_dict(transfer_json("person:zhou")))
    except ValidationError as error:
        print(f"rejected stale proposal: {error}")
    print(f"state unchanged after rejection="
          f"{runtime.snapshot() == before_rejection}")

    replayed = StateRuntime.replay(initial, [
        EventRecord.from_dict(event.to_dict()) for event in runtime.events
    ])
    print(f"replay matches current state={replayed.snapshot() == runtime.snapshot()}")


if __name__ == "__main__":
    main()
