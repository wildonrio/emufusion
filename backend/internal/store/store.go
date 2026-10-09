// Package store holds the small slice of multiplayer state that must
// survive a backend restart: registered devices, submitted schedules, and
// matches. Everything ephemeral (live presence, in-flight signaling,
// ad-hoc want/wanted roster) lives only in the hub's memory -- see
// internal/hub. This is deliberately not a general-purpose database: it is
// a handful of small buckets in one embedded file, sized for a
// friends-and-family alpha, not for scale.
package store

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"time"

	"go.etcd.io/bbolt"
)

var (
	bucketDevices   = []byte("devices")
	bucketSchedules = []byte("schedules")
	bucketMatches   = []byte("matches")
	bucketRoster    = []byte("roster")
)

type Device struct {
	ID         string    `json:"id"`
	SecretHash []byte    `json:"secretHash"`
	Nickname   string    `json:"nickname"`
	CreatedAt  time.Time `json:"createdAt"`
}

type Schedule struct {
	ID         string    `json:"id"`
	DeviceID   string    `json:"deviceId"`
	GameKey    string    `json:"gameKey"`
	System     string    `json:"system"`
	Windows    []Window  `json:"windows"`
	MinPlayers int       `json:"minPlayers"`
	MaxPlayers int       `json:"maxPlayers"`
	CreatedAt  time.Time `json:"createdAt"`
	// Matched is set once this schedule has been folded into a Match, so
	// it is excluded from further matching passes without deleting the
	// record (useful for later debugging/auditing).
	Matched bool `json:"matched"`
}

type Window struct {
	Start time.Time `json:"start"`
	End   time.Time `json:"end"`
}

type MatchState string

const (
	MatchStateScheduled MatchState = "scheduled"
	MatchStateInvited   MatchState = "invited"
	MatchStateActive    MatchState = "active"
	MatchStateEnded     MatchState = "ended"
)

type Match struct {
	ID           string     `json:"id"`
	GameKey      string     `json:"gameKey"`
	System       string     `json:"system"`
	Participants []string   `json:"participants"`
	MinPlayers   int        `json:"minPlayers"`
	MaxPlayers   int        `json:"maxPlayers"`
	ScheduledAt  *time.Time `json:"scheduledAt,omitempty"`
	State        MatchState `json:"state"`
	HostDeviceID string     `json:"hostDeviceId,omitempty"`
	CreatedAt    time.Time  `json:"createdAt"`
}

type Store struct {
	db *bbolt.DB
}

func Open(path string) (*Store, error) {
	db, err := bbolt.Open(path, 0o600, &bbolt.Options{Timeout: 5 * time.Second})
	if err != nil {
		return nil, fmt.Errorf("open bbolt at %s: %w", path, err)
	}
	err = db.Update(func(tx *bbolt.Tx) error {
		for _, bucket := range [][]byte{bucketDevices, bucketSchedules, bucketMatches, bucketRoster} {
			if _, err := tx.CreateBucketIfNotExists(bucket); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		db.Close()
		return nil, fmt.Errorf("create buckets: %w", err)
	}
	return &Store{db: db}, nil
}

func (s *Store) Close() error { return s.db.Close() }

// HashSecret derives the comparable form of a device secret. Secrets are
// server-generated, high-entropy random values (not user-chosen
// passwords), so a single fast SHA-256 is an adequate, appropriately
// lightweight choice here -- slow password-hashing (bcrypt/argon2) exists
// to resist brute-forcing a low-entropy human-chosen secret, which does
// not apply to a random 256-bit value.
func HashSecret(secret string) []byte {
	sum := sha256.Sum256([]byte(secret))
	return sum[:]
}

func (s *Store) CreateDevice(nickname, secret string) (Device, error) {
	device := Device{
		ID:         randomID("dev"),
		SecretHash: HashSecret(secret),
		Nickname:   nickname,
		CreatedAt:  time.Now().UTC(),
	}
	err := s.db.Update(func(tx *bbolt.Tx) error {
		return putJSON(tx.Bucket(bucketDevices), device.ID, device)
	})
	return device, err
}

func (s *Store) GetDevice(id string) (Device, bool, error) {
	var device Device
	found := false
	err := s.db.View(func(tx *bbolt.Tx) error {
		raw := tx.Bucket(bucketDevices).Get([]byte(id))
		if raw == nil {
			return nil
		}
		found = true
		return json.Unmarshal(raw, &device)
	})
	return device, found, err
}

// SetNickname updates a device's display name in place.
func (s *Store) SetNickname(id, nickname string) error {
	return s.db.Update(func(tx *bbolt.Tx) error {
		bucket := tx.Bucket(bucketDevices)
		raw := bucket.Get([]byte(id))
		if raw == nil {
			return fmt.Errorf("device %s not found", id)
		}
		var device Device
		if err := json.Unmarshal(raw, &device); err != nil {
			return err
		}
		device.Nickname = nickname
		return putJSON(bucket, id, device)
	})
}

// VerifySecret does a constant-time comparison against the stored hash so
// that a timing side-channel cannot help an attacker guess a device's
// secret one byte at a time.
func VerifySecret(device Device, secret string) bool {
	return subtle.ConstantTimeCompare(device.SecretHash, HashSecret(secret)) == 1
}

// SaveSchedule takes a pointer so a freshly-generated ID/CreatedAt is
// visible to the caller immediately, not just inside the persisted JSON --
// callers that need the ID right after creating a record (as SaveMatch's
// callers do) would otherwise silently see an empty string.
func (s *Store) SaveSchedule(sch *Schedule) error {
	if sch.ID == "" {
		sch.ID = randomID("sch")
	}
	if sch.CreatedAt.IsZero() {
		sch.CreatedAt = time.Now().UTC()
	}
	return s.db.Update(func(tx *bbolt.Tx) error {
		return putJSON(tx.Bucket(bucketSchedules), sch.ID, *sch)
	})
}

func (s *Store) DeleteSchedule(id string) error {
	return s.db.Update(func(tx *bbolt.Tx) error {
		return tx.Bucket(bucketSchedules).Delete([]byte(id))
	})
}

// OpenSchedulesForGame returns every not-yet-matched schedule for a game
// key, used as the matching pool.
func (s *Store) OpenSchedulesForGame(gameKey string) ([]Schedule, error) {
	var results []Schedule
	err := s.db.View(func(tx *bbolt.Tx) error {
		return tx.Bucket(bucketSchedules).ForEach(func(_, raw []byte) error {
			var sch Schedule
			if err := json.Unmarshal(raw, &sch); err != nil {
				return err
			}
			if sch.GameKey == gameKey && !sch.Matched {
				results = append(results, sch)
			}
			return nil
		})
	})
	return results, err
}

func (s *Store) MarkSchedulesMatched(ids []string) error {
	return s.db.Update(func(tx *bbolt.Tx) error {
		bucket := tx.Bucket(bucketSchedules)
		for _, id := range ids {
			raw := bucket.Get([]byte(id))
			if raw == nil {
				continue
			}
			var sch Schedule
			if err := json.Unmarshal(raw, &sch); err != nil {
				return err
			}
			sch.Matched = true
			if err := putJSON(bucket, id, sch); err != nil {
				return err
			}
		}
		return nil
	})
}

// SaveMatch takes a pointer for the same reason as SaveSchedule: its
// callers immediately need the generated ID to key h.matches and to fill
// in the matchId field of the message they're about to send.
func (s *Store) SaveMatch(m *Match) error {
	if m.ID == "" {
		m.ID = randomID("match")
	}
	if m.CreatedAt.IsZero() {
		m.CreatedAt = time.Now().UTC()
	}
	return s.db.Update(func(tx *bbolt.Tx) error {
		return putJSON(tx.Bucket(bucketMatches), m.ID, *m)
	})
}

func (s *Store) GetMatch(id string) (Match, bool, error) {
	var m Match
	found := false
	err := s.db.View(func(tx *bbolt.Tx) error {
		raw := tx.Bucket(bucketMatches).Get([]byte(id))
		if raw == nil {
			return nil
		}
		found = true
		return json.Unmarshal(raw, &m)
	})
	return m, found, err
}

// RosterRecord is one device's standing interest in one game. It is
// durable (not just held in the hub's memory) because "wants" and
// "wanted" need to survive both the player's own app being closed and a
// backend restart -- a friend opening the app a week later should still
// see "so-and-so wanted to play this," which an in-memory-only roster
// could never promise.
type RosterRecord struct {
	GameKey    string    `json:"gameKey"`
	System     string    `json:"system"`
	DeviceID   string    `json:"deviceId"`
	State      string    `json:"state"` // "wants" | "wanted"
	Since      time.Time `json:"since"`
	MinPlayers int       `json:"minPlayers"`
	MaxPlayers int       `json:"maxPlayers"`
}

func rosterKey(gameKey, deviceID string) string { return gameKey + "|" + deviceID }

func (s *Store) UpsertRoster(record RosterRecord) error {
	return s.db.Update(func(tx *bbolt.Tx) error {
		return putJSON(tx.Bucket(bucketRoster), rosterKey(record.GameKey, record.DeviceID), record)
	})
}

// RosterForGame returns every device that currently wants or has wanted
// to play a game, in no particular order -- callers sort for display.
func (s *Store) RosterForGame(gameKey string) ([]RosterRecord, error) {
	prefix := []byte(gameKey + "|")
	var results []RosterRecord
	err := s.db.View(func(tx *bbolt.Tx) error {
		cursor := tx.Bucket(bucketRoster).Cursor()
		for key, raw := cursor.Seek(prefix); key != nil && hasPrefix(key, prefix); key, raw = cursor.Next() {
			var record RosterRecord
			if err := json.Unmarshal(raw, &record); err != nil {
				return err
			}
			results = append(results, record)
		}
		return nil
	})
	return results, err
}

// AllWantingGameKeys returns every gameKey where the given device
// currently has a roster record, used to re-subscribe a reconnecting
// device to the right roster broadcasts.
func (s *Store) GameKeysForDevice(deviceID string) ([]string, error) {
	var keys []string
	err := s.db.View(func(tx *bbolt.Tx) error {
		return tx.Bucket(bucketRoster).ForEach(func(_, raw []byte) error {
			var record RosterRecord
			if err := json.Unmarshal(raw, &record); err != nil {
				return err
			}
			if record.DeviceID == deviceID {
				keys = append(keys, record.GameKey)
			}
			return nil
		})
	})
	return keys, err
}

func hasPrefix(key, prefix []byte) bool {
	if len(key) < len(prefix) {
		return false
	}
	for i := range prefix {
		if key[i] != prefix[i] {
			return false
		}
	}
	return true
}

func putJSON(bucket *bbolt.Bucket, key string, value any) error {
	raw, err := json.Marshal(value)
	if err != nil {
		return err
	}
	return bucket.Put([]byte(key), raw)
}
