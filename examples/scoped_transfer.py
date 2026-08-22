"""Show retrieval scope, atomic transfer, and out-of-scope rejection."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from state_runtime import Change, Entity, Precondition, Proposal, StateRuntime, ValidationError


def build_runtime() -> StateRuntime:
    return StateRuntime([
        Entity("person:zhou", "person", {"location": "place:station"}),
        Entity("item:letter", "item", {"holder": "person:zhou", "location": "place:station"}),
        Entity("place:station", "place", {"trace": "sealed envelope on the desk"}),
        Entity("place:archive", "place", {"open": False}),
        Entity("player", "player", {"location": "place:station"}),
    ])


def main() -> None:
    runtime = build_runtime()
    transfer = Proposal(
        cause="person:zhou hands the letter to player",
        preconditions=(Precondition("item:letter", "holder", "person:zhou"),),
        changes=(
            Change("person:zhou", {"knows_letter_is_gone": True}),
            Change("item:letter", {"holder": "player", "location": None}),
            Change("place:station", {"trace": "an empty space on the desk"}),
        ),
        scope=("person:zhou", "item:letter", "place:station", "player"),
        duration=0.25,
    )
    event = runtime.commit(transfer)
    print(f"committed event={event.event_id} scope={event.scope}")
    print(f"letter holder={runtime.entities['item:letter'].state['holder']}")

    before = runtime.snapshot()
    try:
        runtime.commit(Proposal(
            cause="attempt to change an unretrieved place",
            changes=(Change("place:archive", {"open": True}),),
            scope=("item:letter", "player"),
        ))
    except ValidationError as error:
        print(f"rejected out-of-scope proposal: {error}")
    print(f"state unchanged after rejection={runtime.snapshot() == before}")


if __name__ == "__main__":
    main()
