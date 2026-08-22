"""Show the boundary between a model proposal and deterministic execution."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from state_runtime import Entity, Proposal, Precondition, StateRuntime, ValidationError


def mock_llm_transfer(expected_holder: str) -> dict:
    """Return JSON-shaped output; a real model could return the same shape."""
    return {
        "cause": "Zhou hands the letter to the player",
        "preconditions": [{
            "entity_id": "item:letter",
            "path": "holder",
            "equals": expected_holder,
        }],
        "changes": [
            {"entity_id": "item:letter", "patch": {"holder": "player"}},
            {"entity_id": "place:station", "patch": {"trace": "empty desk"}},
        ],
        "scope": ["item:letter", "place:station", "player"],
        "duration": 0.25,
    }


def main() -> None:
    runtime = StateRuntime([
        Entity("item:letter", "item", {"holder": "person:zhou"}),
        Entity("place:station", "place", {"trace": "sealed letter"}),
        Entity("player", "player", {"location": "place:station"}),
    ])

    model_output = mock_llm_transfer("person:zhou")
    event = runtime.commit(Proposal.from_dict(model_output))
    print(f"accepted proposal as event {event.event_id}; holder={runtime.entities['item:letter'].state['holder']}")

    before = runtime.snapshot()
    stale_model_output = mock_llm_transfer("person:zhou")
    try:
        runtime.commit(Proposal.from_dict(stale_model_output))
    except ValidationError as error:
        print(f"runtime rejected valid-shaped model output: {error}")
    print(f"state unchanged after rejection={runtime.snapshot() == before}")

    try:
        Proposal.from_dict({"cause": "model forgot changes"})
    except ValidationError as error:
        print(f"parser rejected malformed model output: {error}")


if __name__ == "__main__":
    main()
