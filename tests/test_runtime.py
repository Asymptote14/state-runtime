import unittest

from state_runtime import (
    Change,
    Entity,
    EventRecord,
    Precondition,
    Proposal,
    StateRuntime,
    ValidationError,
)


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

    def test_malformed_change_is_rejected(self):
        for change in (
            Change("item:letter", {}),
            Change("item:letter", {"": "value"}),
            Change("item:letter", {"state..value": "value"}),
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.runtime.commit(Proposal(
                    cause="malformed change",
                    changes=(change,),
                ))

    def test_scope_must_cover_reads_and_writes(self):
        event = self.runtime.commit(Proposal(
            cause="read and write within retrieved scope",
            preconditions=(Precondition("item:letter", "holder", "npc:zhou"),),
            changes=(Change("item:letter", {"holder": "player"}),),
            scope=("item:letter", "npc:zhou", "player"),
        ))
        self.assertEqual(event.scope, ("item:letter", "npc:zhou", "player"))

        with self.assertRaisesRegex(ValidationError, "outside scope"):
            self.runtime.commit(Proposal(
                cause="write outside retrieved scope",
                changes=(Change("scene:station", {"mark": "changed"}),),
                scope=("item:letter",),
            ))

    def test_scope_rejects_unknown_or_duplicate_entities(self):
        for scope, message in (
            (("item:letter", "item:letter"), "duplicate"),
            (("item:missing",), "unknown scope"),
        ):
            with self.subTest(scope=scope), self.assertRaisesRegex(ValidationError, message):
                self.runtime.commit(Proposal(
                    cause="invalid scope",
                    changes=(Change("item:letter", {"holder": "player"}),),
                    scope=scope,
                ))

    def test_non_finite_duration_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "duration"):
            self.runtime.commit(Proposal(
                cause="invalid time",
                changes=(Change("scene:station", {"mark": "unchanged"}),),
                duration=float("nan"),
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

    def test_prepare_does_not_mutate_until_commit(self):
        proposal = Proposal(
            cause="prepare a transfer",
            preconditions=(Precondition("item:letter", "holder", "npc:zhou"),),
            changes=(Change("item:letter", {"holder": "player"}),),
        )
        before = self.runtime.snapshot()
        prepared = self.runtime.prepare(proposal)
        self.assertEqual(self.runtime.snapshot(), before)
        self.runtime.commit_prepared(prepared)
        self.assertEqual(self.runtime.entities["item:letter"].state["holder"], "player")

    def test_stale_prepared_event_is_rejected(self):
        prepared = self.runtime.prepare(Proposal(
            cause="prepare once",
            changes=(Change("scene:station", {"mark": "first"}),),
        ))
        self.runtime.commit(Proposal(
            cause="newer event",
            changes=(Change("scene:station", {"mark": "newer"}),),
        ))
        with self.assertRaisesRegex(ValidationError, "stale"):
            self.runtime.commit_prepared(prepared)

    def test_snapshot_and_event_replay_restore_same_state(self):
        initial = [entity.clone() for entity in self.runtime.entities.values()]
        self.runtime.commit(Proposal(
            cause="advance the clock",
            changes=(Change("scene:station", {"mark": "changed"}),),
            duration=0.5,
        ))
        snapshot = self.runtime.snapshot()
        restored = StateRuntime.from_snapshot(snapshot)
        replayed = StateRuntime.replay(initial, self.runtime.events)
        self.assertEqual(restored.snapshot(), snapshot)
        self.assertEqual(replayed.snapshot(), snapshot)

    def test_snapshot_round_trip_tolerates_float_clock_accumulation(self):
        initial = [entity.clone() for entity in self.runtime.entities.values()]
        for duration in (0.1, 0.2):
            self.runtime.commit(Proposal(
                cause="advance by a fractional duration",
                changes=(Change("scene:station", {"mark": str(duration)}),),
                duration=duration,
            ))

        snapshot = self.runtime.snapshot()
        restored = StateRuntime.from_snapshot(snapshot)
        replayed = StateRuntime.replay(initial, self.runtime.events)

        self.assertEqual(restored.snapshot(), snapshot)
        self.assertEqual(replayed.snapshot(), snapshot)

    def test_replay_rejects_invalid_event_duration(self):
        initial = [entity.clone() for entity in self.runtime.entities.values()]
        event = self.runtime.commit(Proposal(
            cause="valid event",
            changes=(Change("scene:station", {"mark": "changed"}),),
        ))
        invalid = EventRecord(
            event.event_id,
            event.clock,
            -1.0,
            event.cause,
            event.entity_ids,
            event.changes,
            event.visible_to,
            event.metadata,
        )
        with self.assertRaisesRegex(ValidationError, "duration"):
            StateRuntime.replay(initial, [invalid])

    def test_replay_rejects_tampered_entity_list(self):
        initial = [entity.clone() for entity in self.runtime.entities.values()]
        event = self.runtime.commit(Proposal(
            cause="valid event",
            changes=(Change("scene:station", {"mark": "changed"}),),
        ))
        invalid = EventRecord(
            event.event_id,
            event.clock,
            event.duration,
            event.cause,
            ("scene:station", "player"),
            event.changes,
            event.visible_to,
            event.metadata,
        )
        with self.assertRaisesRegex(ValidationError, "entity_ids"):
            StateRuntime.replay(initial, [invalid])

    def test_replay_rejects_scope_outside_initial_entities(self):
        initial = [entity.clone() for entity in self.runtime.entities.values()]
        event = self.runtime.commit(Proposal(
            cause="scoped event",
            changes=(Change("scene:station", {"mark": "changed"}),),
            scope=("scene:station",),
        ))
        invalid = EventRecord(
            event.event_id,
            event.clock,
            event.duration,
            event.cause,
            event.entity_ids,
            event.changes,
            event.visible_to,
            event.metadata,
            ("scene:station", "entity:missing"),
        )
        with self.assertRaisesRegex(ValidationError, "scope"):
            StateRuntime.replay(initial, [invalid])


if __name__ == "__main__":
    unittest.main()
