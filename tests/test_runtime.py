import unittest

from state_runtime import Change, Entity, Precondition, Proposal, StateRuntime, ValidationError


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = StateRuntime([
            Entity("npc:zhou", "npc", {"location": "scene:station", "known": []}),
            Entity("npc:arin", "npc", {"location": "scene:cafe", "known": []}),
            Entity("item:letter", "item", {"holder": "npc:zhou", "location": "scene:station"}),
            Entity("scene:station", "scene", {"mark": "rain on glass"}),
            Entity("player", "player", {"location": "scene:station"}),
        ])

    def test_atomic_multi_entity_commit(self):
        event = self.runtime.commit(Proposal(
            cause="Zhou hands the letter to the player",
            preconditions=(Precondition("item:letter", "holder", "npc:zhou"),),
            changes=(
                Change("npc:zhou", {"known": ["the letter was taken"]}),
                Change("item:letter", {"holder": "player", "location": None}),
                Change("scene:station", {"mark": "an empty space under the ledger"}),
            ),
            duration=0.25,
            visible_to=("player",),
        ))
        self.assertEqual(event.entity_ids, ("npc:zhou", "item:letter", "scene:station"))
        self.assertEqual(self.runtime.entities["item:letter"].state["holder"], "player")
        self.assertEqual(self.runtime.clock, 0.25)

    def test_failed_proposal_changes_nothing(self):
        before = self.runtime.snapshot()
        with self.assertRaises(ValidationError):
            self.runtime.commit(Proposal(
                cause="invalid transfer",
                preconditions=(Precondition("item:letter", "holder", "player"),),
                changes=(
                    Change("item:letter", {"holder": "npc:arin"}),
                    Change("scene:station", {"mark": "should not exist"}),
                ),
            ))
        self.assertEqual(self.runtime.snapshot(), before)

    def test_unknown_reference_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "unknown entity"):
            self.runtime.commit(Proposal(
                cause="dangling reference",
                changes=(Change("item:ghost", {"holder": "player"}),),
            ))

    def test_visibility_is_separate_from_full_log(self):
        self.runtime.commit(Proposal(
            cause="Zhou reads a private note",
            changes=(Change("npc:zhou", {"known": ["private secret"]}),),
            visible_to=("npc:zhou",),
        ))
        self.assertEqual(len(self.runtime.visible_events("npc:zhou")), 1)
        self.assertEqual(self.runtime.visible_events("npc:arin"), [])
        self.assertEqual(len(self.runtime.events), 1)


if __name__ == "__main__":
    unittest.main()
