package hub

import (
	"encoding/json"
	"path/filepath"
	"testing"
	"time"

	"github.com/pegasus-lucent/multiplayer-backend/internal/protocol"
	"github.com/pegasus-lucent/multiplayer-backend/internal/store"
)

func newTestHub(t *testing.T) *Hub {
	t.Helper()
	db, err := store.Open(filepath.Join(t.TempDir(), "test.db"))
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	return New(db)
}

// awaitEnvelope reads the next message of the given type from a
// connection's Send channel, failing the test if it doesn't arrive
// quickly -- every path under test here is synchronous, so a slow arrival
// means the logic under test never fired at all.
func awaitEnvelope(t *testing.T, conn *Connection, msgType string) protocol.Envelope {
	t.Helper()
	deadline := time.After(2 * time.Second)
	for {
		select {
		case env := <-conn.Send:
			if env.Type == msgType {
				return env
			}
			// Keep looking -- e.g. a roster.update can arrive before the
			// invite.available this particular assertion cares about.
		case <-deadline:
			t.Fatalf("timed out waiting for %q on device %s", msgType, conn.DeviceID)
		}
	}
}

func assertNoEnvelope(t *testing.T, conn *Connection, msgType string) {
	t.Helper()
	deadline := time.After(200 * time.Millisecond)
	for {
		select {
		case env := <-conn.Send:
			if env.Type == msgType {
				t.Fatalf("unexpected %q on device %s", msgType, conn.DeviceID)
			}
		case <-deadline:
			return
		}
	}
}

func TestInstantMatchOnMutualWant(t *testing.T) {
	h := newTestHub(t)
	a := h.Connect("deviceA", "Alice")
	b := h.Connect("deviceB", "Bob")

	h.HandleWantSet("deviceA", "Alice", protocol.WantSet{
		GameKey: "g1", System: "nes", Want: true, MinPlayers: 2, MaxPlayers: 2,
	})
	roster := awaitEnvelope(t, a, "roster.update")
	var update protocol.RosterUpdate
	mustDecode(t, roster, &update)
	if len(update.Entries) != 1 || update.Entries[0].State != "wants" {
		t.Fatalf("expected exactly one 'wants' entry after A alone, got %+v", update.Entries)
	}
	// Only one candidate so far -- no invite should fire yet.
	assertNoEnvelope(t, a, "invite.available")

	h.HandleWantSet("deviceB", "Bob", protocol.WantSet{
		GameKey: "g1", System: "nes", Want: true, MinPlayers: 2, MaxPlayers: 2,
	})

	inviteA := awaitEnvelope(t, a, "invite.available")
	inviteB := awaitEnvelope(t, b, "invite.available")
	var payloadA, payloadB protocol.InviteAvailable
	mustDecode(t, inviteA, &payloadA)
	mustDecode(t, inviteB, &payloadB)
	if payloadA.MatchID == "" || payloadA.MatchID != payloadB.MatchID {
		t.Fatalf("expected both sides to receive the same matchId, got %q vs %q", payloadA.MatchID, payloadB.MatchID)
	}
	if len(payloadA.Participants) != 2 {
		t.Fatalf("expected 2 participants, got %v", payloadA.Participants)
	}
}

func TestMinPlayersPreventsPrematureMatch(t *testing.T) {
	h := newTestHub(t)
	a := h.Connect("deviceA", "Alice")
	b := h.Connect("deviceB", "Bob")
	c := h.Connect("deviceC", "Carol")

	// Alice won't play unless at least 3 people (including her) are in.
	h.HandleWantSet("deviceA", "Alice", protocol.WantSet{
		GameKey: "g1", System: "nes", Want: true, MinPlayers: 3, MaxPlayers: 4,
	})
	h.HandleWantSet("deviceB", "Bob", protocol.WantSet{
		GameKey: "g1", System: "nes", Want: true, MinPlayers: 2, MaxPlayers: 4,
	})
	// Drain roster.update noise before asserting silence.
	drainRoster(t, a)
	drainRoster(t, b)
	assertNoEnvelope(t, a, "invite.available")
	assertNoEnvelope(t, b, "invite.available")

	// A third player arrives -- now Alice's minimum of 3 is satisfiable.
	h.HandleWantSet("deviceC", "Carol", protocol.WantSet{
		GameKey: "g1", System: "nes", Want: true, MinPlayers: 2, MaxPlayers: 4,
	})
	inviteA := awaitEnvelope(t, a, "invite.available")
	var payload protocol.InviteAvailable
	mustDecode(t, inviteA, &payload)
	if len(payload.Participants) != 3 {
		t.Fatalf("expected all 3 players once Alice's minimum is met, got %v", payload.Participants)
	}
	_ = c
}

func TestScheduleMatchOverlap(t *testing.T) {
	h := newTestHub(t)
	a := h.Connect("deviceA", "Alice")
	b := h.Connect("deviceB", "Bob")

	base := time.Now().UTC().Add(time.Hour).Truncate(time.Second)
	h.HandleScheduleSubmit("deviceA", protocol.ScheduleSubmit{
		GameKey: "g1", System: "nes", MinPlayers: 2, MaxPlayers: 2,
		Windows: []protocol.ScheduleWindow{{
			Start: base.Format(time.RFC3339),
			End:   base.Add(2 * time.Hour).Format(time.RFC3339),
		}},
	})
	assertNoEnvelope(t, a, "match.scheduled") // only one schedule so far

	overlapStart := base.Add(time.Hour)
	h.HandleScheduleSubmit("deviceB", protocol.ScheduleSubmit{
		GameKey: "g1", System: "nes", MinPlayers: 2, MaxPlayers: 2,
		Windows: []protocol.ScheduleWindow{{
			Start: overlapStart.Format(time.RFC3339),
			End:   overlapStart.Add(2 * time.Hour).Format(time.RFC3339),
		}},
	})

	scheduledA := awaitEnvelope(t, a, "match.scheduled")
	scheduledB := awaitEnvelope(t, b, "match.scheduled")
	var payloadA, payloadB protocol.MatchScheduled
	mustDecode(t, scheduledA, &payloadA)
	mustDecode(t, scheduledB, &payloadB)
	if payloadA.MatchID == "" || payloadA.MatchID != payloadB.MatchID {
		t.Fatalf("expected a shared, non-empty matchId on both sides, got %q vs %q", payloadA.MatchID, payloadB.MatchID)
	}
	if payloadA.ScheduledAt != overlapStart.Format(time.RFC3339) {
		t.Fatalf("expected scheduledAt=%s, got %s", overlapStart.Format(time.RFC3339), payloadA.ScheduledAt)
	}
	if len(payloadA.Participants) != 2 {
		t.Fatalf("expected 2 participants, got %v", payloadA.Participants)
	}
}

func TestInviteRespondRejectsNonParticipant(t *testing.T) {
	h := newTestHub(t)
	a := h.Connect("deviceA", "Alice")
	h.Connect("deviceB", "Bob")
	h.Connect("deviceC", "Carol") // never part of the match below

	h.HandleWantSet("deviceA", "Alice", protocol.WantSet{GameKey: "g1", Want: true, MinPlayers: 2, MaxPlayers: 2})
	h.HandleWantSet("deviceB", "Bob", protocol.WantSet{GameKey: "g1", Want: true, MinPlayers: 2, MaxPlayers: 2})
	inviteA := awaitEnvelope(t, a, "invite.available")
	var payload protocol.InviteAvailable
	mustDecode(t, inviteA, &payload)

	// Carol was never invited; her role claim must not succeed.
	h.HandleRoleClaim("deviceC", protocol.MatchRoleClaim{MatchID: payload.MatchID, Role: "host"})
	assertNoEnvelope(t, a, "match.role_assigned")
}

func drainRoster(t *testing.T, conn *Connection) {
	t.Helper()
	for {
		select {
		case env := <-conn.Send:
			if env.Type != "roster.update" {
				t.Fatalf("expected only roster.update while draining, got %q", env.Type)
			}
		case <-time.After(100 * time.Millisecond):
			return
		}
	}
}

func mustDecode(t *testing.T, env protocol.Envelope, target any) {
	t.Helper()
	if err := json.Unmarshal(env.Payload, target); err != nil {
		t.Fatalf("decode %s payload: %v", env.Type, err)
	}
}
