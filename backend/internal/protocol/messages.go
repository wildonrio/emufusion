// Package protocol defines the JSON message contract between a Lucent
// device and the multiplayer backend over one persistent WebSocket per
// device. The backend only ever carries presence, roster, scheduling, and
// WebRTC signaling data here -- game input/video/audio always travels
// peer-to-peer over a WebRTC DataChannel once two devices are matched, never
// through this connection.
package protocol

import "encoding/json"

// Envelope is the outer shape of every message in both directions. Payload
// is left raw so the hub can dispatch on Type before parsing the rest.
type Envelope struct {
	Type    string          `json:"type"`
	Payload json.RawMessage `json:"payload,omitempty"`
}

// ---- Client -> server payloads ----

type Heartbeat struct{}

type WantSet struct {
	GameKey    string `json:"gameKey"`
	System     string `json:"system"`
	Want       bool   `json:"want"`
	MinPlayers int    `json:"minPlayers"`
	MaxPlayers int    `json:"maxPlayers"`
}

type ScheduleWindow struct {
	Start string `json:"start"` // RFC3339
	End   string `json:"end"`   // RFC3339
}

type ScheduleSubmit struct {
	GameKey    string           `json:"gameKey"`
	System     string           `json:"system"`
	Windows    []ScheduleWindow `json:"windows"`
	MinPlayers int              `json:"minPlayers"`
	MaxPlayers int              `json:"maxPlayers"`
}

type ScheduleCancel struct {
	ScheduleID string `json:"scheduleId"`
}

type InviteRespond struct {
	MatchID string `json:"matchId"`
	Accept  bool   `json:"accept"`
}

type MatchRoleClaim struct {
	MatchID string `json:"matchId"`
	Role    string `json:"role"` // only "host" is meaningful today
}

type Signal struct {
	MatchID    string          `json:"matchId"`
	ToDeviceID string          `json:"toDeviceId"`
	Payload    json.RawMessage `json:"payload"`
}

// ---- Server -> client payloads ----

type IdentityAck struct {
	DeviceID string `json:"deviceId"`
	Nickname string `json:"nickname"`
}

type RosterEntry struct {
	DeviceID   string `json:"deviceId"`
	Nickname   string `json:"nickname"`
	State      string `json:"state"` // "wants" | "wanted"
	Since      string `json:"since"` // RFC3339
	MinPlayers int    `json:"minPlayers"`
	MaxPlayers int    `json:"maxPlayers"`
}

type RosterUpdate struct {
	GameKey string        `json:"gameKey"`
	Entries []RosterEntry `json:"entries"`
}

type MatchScheduled struct {
	MatchID      string   `json:"matchId"`
	GameKey      string   `json:"gameKey"`
	ScheduledAt  string   `json:"scheduledAt"` // RFC3339
	Participants []string `json:"participants"`
	MinPlayers   int      `json:"minPlayers"`
	MaxPlayers   int      `json:"maxPlayers"`
	Full         bool     `json:"full"`
}

type InviteAvailable struct {
	MatchID      string   `json:"matchId"`
	GameKey      string   `json:"gameKey"`
	Participants []string `json:"participants"`
}

type MatchRoleAssigned struct {
	MatchID      string `json:"matchId"`
	HostDeviceID string `json:"hostDeviceId"`
}

type SignalRelay struct {
	MatchID      string          `json:"matchId"`
	FromDeviceID string          `json:"fromDeviceId"`
	Payload      json.RawMessage `json:"payload"`
}

type MatchEnded struct {
	MatchID string `json:"matchId"`
	Reason  string `json:"reason"`
}

type ErrorMessage struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

// Encode wraps a typed payload into an Envelope ready for json.Marshal.
func Encode(msgType string, payload any) (Envelope, error) {
	raw, err := json.Marshal(payload)
	if err != nil {
		return Envelope{}, err
	}
	return Envelope{Type: msgType, Payload: raw}, nil
}
