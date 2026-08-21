"""Four small examples of the runtime's public contract."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from state_runtime import Change, Entity, Precondition, Proposal, StateRuntime, ValidationError


def main() -> None:
    runtime = StateRuntime([
        Entity("person:zhou", "person", {"location": "station", "knows": []}),
        Entity("person:arin", "person", {"location": "cafe", "knows": []}),
        Entity("item:letter", "item", {"holder": "person:zhou", "location": "station"}),
        Entity("place:station", "place", {"trace": "wet ledger"}),
        Entity("player", "player", {"location": "station"}),
    ])

    runtime.commit(Proposal(
        cause="person:zhou transfers the letter to player",
        preconditions=(Precondition("item:letter", "holder", "person:zhou"),),
        changes=(
            Change("person:zhou", {"knows": ["the letter is gone"]}),
            Change("item:letter", {"holder": "player", "location": None}),
            Change("place:station", {"trace": "an empty slot in the wet ledger"}),
        ),
        duration=0.25,
        visible_to=("player",),
    ))

    try:
        runtime.commit(Proposal(
            cause="attempt to return a letter that is no longer held here",
            preconditions=(Precondition("item:letter", "holder", "person:zhou"),),
            changes=(Change("item:letter", {"holder": "person:zhou"}),),
        ))
    except ValidationError as error:
        print(f"rejected atomically: {error}")

    print(f"clock={runtime.clock}")
    print(f"events={len(runtime.events)}")
    print(f"letter={runtime.entities['item:letter'].state}")


if __name__ == "__main__":
    main()
