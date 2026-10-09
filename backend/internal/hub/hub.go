// Package hub is the live heart of the multiplayer backend: it tracks
// which devices are currently connected, routes their messages, keeps the
// per-game want/wanted roster in sync, runs both the instant and
// scheduled matching logic, and relays WebRTC signaling between matched
// peers. It never touches game input, video, or audio -- those travel
// peer-to-peer once two devices are matched, entirely outside this
// process.
package hub

import (
	"log"
	"sort"
	"sync"
	"time"

	"github.com/emufusion/multiplayer-backend/internal/protocol"
	"github.com/emufusion/multiplayer-backend/internal/store"
)

// heartbeatTimeout is how long a device can go without a heartbeat before
// its roster entries flip from "wants" to "wanted" and its connection is
// considered gone. Chosen well above the client's expected ~20s heartbeat
// interval to tolerate a couple of missed beats on a flaky mobile network
// without flapping a player's visible status.
const heartbeatTimeout = 60 * time.Second

// sweepInterval is how often the background sweeper checks for stale
// connections.
const sweepInterval = 10 * time.Second

// minScheduleOverlap is the shortest overlapping availability window this
// backend will turn into a scheduled match; anything shorter is very
// unlikely to be enough time to actually start playing.
const minScheduleOverlap = 5 * time.Minute

// Connection is one device's live WebSocket session.
type Connection struct {
	DeviceID string
	Nickname string
	Send     chan protocol.Envelope
}

type liveDevice struct {
	conn          *Connection
	lastHeartbeat time.Time
}

type Hub struct {
	store *store.Store

	mu      sync.Mutex
	live    map[string]*liveDevice  // deviceId -> live state, only while connected
	matches map[string]*store.Match // matchId -> in-memory copy of active/invited matches
}

func New(s *store.Store) *Hub {
	return &Hub{
		store:   s,
		live:    make(map[string]*liveDevice),
		matches: make(map[string]*store.Match),
	}
}

// Run starts the background staleness sweeper. It blocks until stop is
// closed, so call it in its own goroutine.
func (h *Hub) Run(stop <-chan struct{}) {
	ticker := time.NewTicker(sweepInterval)
	defer ticker.Stop()
	for {
		select {
		case <-stop:
			return
		case <-ticker.C:
			h.sweepStale()
		}
	}
}

// Connect registers a newly-authenticated device's live connection and
// returns it with its Send channel ready. It replaces any prior
// connection for the same device (a reconnect), and pushes the current
// roster state for every game this device has a standing interest in so
// the client doesn't need a separate "give me the current state" request.
func (h *Hub) Connect(deviceID, nickname string) *Connection {
	conn := &Connection{DeviceID: deviceID, Nickname: nickname, Send: make(chan protocol.Envelope, 64)}
	h.mu.Lock()
	h.live[deviceID] = &liveDevice{conn: conn, lastHeartbeat: time.Now()}
	h.mu.Unlock()

	if keys, err := h.store.GameKeysForDevice(deviceID); err != nil {
		log.Printf("hub: GameKeysForDevice(%s): %v", deviceID, err)
	} else {
		for _, key := range keys {
			h.broadcastRoster(key)
		}
	}
	return conn
}

// Disconnect removes a device's live connection. It deliberately does NOT
// immediately flip that device's roster entries to "wanted" -- a brief
// drop-and-reconnect (very common on mobile networks) shouldn't visibly
// flap a player's status. The sweeper handles the actual flip once the
// heartbeat has genuinely gone stale.
func (h *Hub) Disconnect(deviceID string) {
	h.mu.Lock()
	if live, ok := h.live[deviceID]; ok && live.conn != nil {
		delete(h.live, deviceID)
	}
	h.mu.Unlock()
}

func (h *Hub) HandleHeartbeat(deviceID string) {
	h.mu.Lock()
	if live, ok := h.live[deviceID]; ok {
		live.lastHeartbeat = time.Now()
	}
	h.mu.Unlock()
}

// ---- Roster / want-set ----

func (h *Hub) HandleWantSet(deviceID, nickname string, msg protocol.WantSet) {
	state := "wanted"
	if msg.Want {
		state = "wants"
	}
	record := store.RosterRecord{
		GameKey:    msg.GameKey,
		System:     msg.System,
		DeviceID:   deviceID,
		State:      state,
		Since:      time.Now().UTC(),
		MinPlayers: msg.MinPlayers,
		MaxPlayers: msg.MaxPlayers,
	}
	if err := h.store.UpsertRoster(record); err != nil {
		log.Printf("hub: UpsertRoster: %v", err)
		return
	}
	h.broadcastRoster(msg.GameKey)
	if msg.Want {
		h.tryInstantMatch(msg.GameKey, msg.System)
	}
}

func (h *Hub) broadcastRoster(gameKey string) {
	records, err := h.store.RosterForGame(gameKey)
	if err != nil {
		log.Printf("hub: RosterForGame(%s): %v", gameKey, err)
		return
	}
	entries := make([]protocol.RosterEntry, 0, len(records))
	for _, r := range records {
		nickname := h.nicknameFor(r.DeviceID)
		entries = append(entries, protocol.RosterEntry{
			DeviceID:   r.DeviceID,
			Nickname:   nickname,
			State:      r.State,
			Since:      r.Since.Format(time.RFC3339),
			MinPlayers: r.MinPlayers,
			MaxPlayers: r.MaxPlayers,
		})
	}
	// Wants first (oldest first, so people who've been waiting longest
	// show up first), then wanted (most-recently-left first).
	sort.SliceStable(entries, func(i, j int) bool {
		if (entries[i].State == "wants") != (entries[j].State == "wants") {
			return entries[i].State == "wants"
		}
		if entries[i].State == "wants" {
			return entries[i].Since < entries[j].Since
		}
		return entries[i].Since > entries[j].Since
	})

	env, err := protocol.Encode("roster.update", protocol.RosterUpdate{GameKey: gameKey, Entries: entries})
	if err != nil {
		log.Printf("hub: encode roster.update: %v", err)
		return
	}
	deviceIDs := make([]string, 0, len(records))
	for _, r := range records {
		deviceIDs = append(deviceIDs, r.DeviceID)
	}
	h.sendToDevices(deviceIDs, env)
}

func (h *Hub) nicknameFor(deviceID string) string {
	h.mu.Lock()
	if live, ok := h.live[deviceID]; ok {
		nickname := live.conn.Nickname
		h.mu.Unlock()
		return nickname
	}
	h.mu.Unlock()
	device, found, err := h.store.GetDevice(deviceID)
	if err != nil || !found {
		return "Player"
	}
	return device.Nickname
}

// ---- Instant ad-hoc matching ----

func (h *Hub) tryInstantMatch(gameKey, system string) {
	records, err := h.store.RosterForGame(gameKey)
	if err != nil {
		log.Printf("hub: RosterForGame(%s): %v", gameKey, err)
		return
	}
	var candidates []store.RosterRecord
	for _, r := range records {
		if r.State != "wants" {
			continue
		}
		if !h.isOnline(r.DeviceID) {
			continue
		}
		if h.inUnresolvedMatch(r.DeviceID, gameKey) {
			continue
		}
		candidates = append(candidates, r)
	}
	if len(candidates) < 2 {
		return
	}
	sort.Slice(candidates, func(i, j int) bool { return candidates[i].Since.Before(candidates[j].Since) })
	group := stableMinMaxGroup(candidates)
	if len(group) < 2 {
		return
	}
	participants := make([]string, 0, len(group))
	for _, r := range group {
		participants = append(participants, r.DeviceID)
	}
	match := store.Match{
		GameKey:      gameKey,
		System:       system,
		Participants: participants,
		MinPlayers:   maxMinPlayers(group),
		MaxPlayers:   minMaxPlayers(group),
		State:        store.MatchStateInvited,
	}
	if err := h.store.SaveMatch(&match); err != nil {
		log.Printf("hub: SaveMatch: %v", err)
		return
	}
	h.mu.Lock()
	h.matches[match.ID] = &match
	h.mu.Unlock()

	env, err := protocol.Encode("invite.available", protocol.InviteAvailable{
		MatchID: match.ID, GameKey: gameKey, Participants: participants,
	})
	if err != nil {
		log.Printf("hub: encode invite.available: %v", err)
		return
	}
	h.sendToDevices(participants, env)
}

// stableMinMaxGroup repeatedly drops any candidate whose own MinPlayers
// requirement exceeds the remaining group size, until the group is either
// stable (every remaining member's MinPlayers is satisfied) or too small
// to be a match at all. This is a deliberately simple, greedy heuristic --
// documented as an alpha limitation, not a claim of optimality across many
// simultaneous conflicting constraints.
func stableMinMaxGroup(candidates []store.RosterRecord) []store.RosterRecord {
	group := candidates
	for {
		if len(group) < 2 {
			return nil
		}
		ceiling := minMaxPlayers(group)
		if len(group) > ceiling {
			group = group[:ceiling]
		}
		trimmed := group[:0:0]
		for _, r := range group {
			if r.MinPlayers <= len(group) {
				trimmed = append(trimmed, r)
			}
		}
		if len(trimmed) == len(group) {
			return group
		}
		group = trimmed
	}
}

func maxMinPlayers(group []store.RosterRecord) int {
	result := 2
	for _, r := range group {
		if r.MinPlayers > result {
			result = r.MinPlayers
		}
	}
	return result
}

func minMaxPlayers(group []store.RosterRecord) int {
	result := 8 // native port ceiling for the libretro family; a reasonable default cap
	for _, r := range group {
		if r.MaxPlayers > 0 && r.MaxPlayers < result {
			result = r.MaxPlayers
		}
	}
	return result
}

func (h *Hub) inUnresolvedMatch(deviceID, gameKey string) bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	for _, m := range h.matches {
		if m.GameKey != gameKey {
			continue
		}
		if m.State != store.MatchStateInvited && m.State != store.MatchStateActive {
			continue
		}
		for _, p := range m.Participants {
			if p == deviceID {
				return true
			}
		}
	}
	return false
}

func (h *Hub) isOnline(deviceID string) bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	_, ok := h.live[deviceID]
	return ok
}

// ---- Scheduling ----

func (h *Hub) HandleScheduleSubmit(deviceID string, msg protocol.ScheduleSubmit) {
	windows := make([]store.Window, 0, len(msg.Windows))
	for _, w := range msg.Windows {
		start, err := time.Parse(time.RFC3339, w.Start)
		if err != nil {
			log.Printf("hub: bad schedule window start %q: %v", w.Start, err)
			continue
		}
		end, err := time.Parse(time.RFC3339, w.End)
		if err != nil || !end.After(start) {
			log.Printf("hub: bad schedule window end %q: %v", w.End, err)
			continue
		}
		windows = append(windows, store.Window{Start: start, End: end})
	}
	if len(windows) == 0 {
		return
	}
	sch := store.Schedule{
		DeviceID:   deviceID,
		GameKey:    msg.GameKey,
		System:     msg.System,
		Windows:    windows,
		MinPlayers: msg.MinPlayers,
		MaxPlayers: msg.MaxPlayers,
	}
	if err := h.store.SaveSchedule(&sch); err != nil {
		log.Printf("hub: SaveSchedule: %v", err)
		return
	}
	h.tryScheduleMatch(msg.GameKey, msg.System)
}

func (h *Hub) HandleScheduleCancel(deviceID, scheduleID string) {
	if err := h.store.DeleteSchedule(scheduleID); err != nil {
		log.Printf("hub: DeleteSchedule: %v", err)
	}
}

type scheduleEvent struct {
	at    time.Time
	delta int
	sch   *store.Schedule
}

// tryScheduleMatch sweeps every open schedule for a game and looks for
// the largest time window with enough overlapping, mutually-satisfiable
// participants. See stableMinMaxGroup's doc comment for the same
// "deliberately simple, not globally optimal" caveat applied to time
// windows instead of an instant roster.
func (h *Hub) tryScheduleMatch(gameKey, system string) {
	schedules, err := h.store.OpenSchedulesForGame(gameKey)
	if err != nil {
		log.Printf("hub: OpenSchedulesForGame(%s): %v", gameKey, err)
		return
	}
	if len(schedules) < 2 {
		return
	}
	byDevice := make(map[string]*store.Schedule, len(schedules))
	var events []scheduleEvent
	for i := range schedules {
		sch := &schedules[i]
		byDevice[sch.DeviceID] = sch
		for _, w := range sch.Windows {
			events = append(events, scheduleEvent{at: w.Start, delta: 1, sch: sch})
			events = append(events, scheduleEvent{at: w.End, delta: -1, sch: sch})
		}
	}
	sort.Slice(events, func(i, j int) bool { return events[i].at.Before(events[j].at) })

	active := make(map[string]*store.Schedule)
	for i := 0; i < len(events); i++ {
		if events[i].delta == 1 {
			active[events[i].sch.DeviceID] = events[i].sch
		} else {
			delete(active, events[i].sch.DeviceID)
		}
		if i+1 >= len(events) {
			break
		}
		intervalEnd := events[i+1].at
		intervalStart := events[i].at
		if intervalEnd.Sub(intervalStart) < minScheduleOverlap || len(active) < 2 {
			continue
		}
		group := make([]store.RosterRecord, 0, len(active))
		for _, sch := range active {
			group = append(group, store.RosterRecord{
				DeviceID: sch.DeviceID, MinPlayers: sch.MinPlayers, MaxPlayers: sch.MaxPlayers,
			})
		}
		sort.Slice(group, func(a, b int) bool {
			return byDevice[group[a].DeviceID].CreatedAt.Before(byDevice[group[b].DeviceID].CreatedAt)
		})
		stable := stableMinMaxGroup(group)
		if len(stable) < 2 {
			continue
		}
		h.commitScheduledMatch(gameKey, system, stable, byDevice, intervalStart)
		return // recompute fresh next time; avoids double-booking within one pass
	}
}

func (h *Hub) commitScheduledMatch(gameKey, system string, group []store.RosterRecord,
	byDevice map[string]*store.Schedule, scheduledAt time.Time) {
	participants := make([]string, 0, len(group))
	scheduleIDs := make([]string, 0, len(group))
	for _, r := range group {
		participants = append(participants, r.DeviceID)
		scheduleIDs = append(scheduleIDs, byDevice[r.DeviceID].ID)
	}
	max := minMaxPlayers(group)
	match := store.Match{
		GameKey:      gameKey,
		System:       system,
		Participants: participants,
		MinPlayers:   maxMinPlayers(group),
		MaxPlayers:   max,
		ScheduledAt:  &scheduledAt,
		State:        store.MatchStateScheduled,
	}
	if err := h.store.SaveMatch(&match); err != nil {
		log.Printf("hub: SaveMatch: %v", err)
		return
	}
	if err := h.store.MarkSchedulesMatched(scheduleIDs); err != nil {
		log.Printf("hub: MarkSchedulesMatched: %v", err)
	}
	h.mu.Lock()
	h.matches[match.ID] = &match
	h.mu.Unlock()

	env, err := protocol.Encode("match.scheduled", protocol.MatchScheduled{
		MatchID: match.ID, GameKey: gameKey, ScheduledAt: scheduledAt.Format(time.RFC3339),
		Participants: participants, MinPlayers: match.MinPlayers, MaxPlayers: match.MaxPlayers,
		Full: len(participants) >= max,
	})
	if err != nil {
		log.Printf("hub: encode match.scheduled: %v", err)
		return
	}
	h.sendToDevices(participants, env)
}

// ---- Invite response / host election / signaling ----

// HandleInviteRespond and HandleRoleClaim below take care to do every read
// AND write of a shared *store.Match under a single critical section, and
// to copy out only plain values (never the pointer itself) before
// unlocking -- match objects are mutated in place by whichever goroutine
// handles the next message for them, so touching one outside the lock, or
// dereferencing it after a failed map lookup, is a real nil-pointer/data-race
// bug, not just a style nit.

func (h *Hub) HandleInviteRespond(deviceID string, msg protocol.InviteRespond) {
	if !msg.Accept {
		h.endMatch(msg.MatchID, "declined")
		return
	}
	var snapshot store.Match
	found := false
	h.mu.Lock()
	if match, ok := h.matches[msg.MatchID]; ok && contains(match.Participants, deviceID) {
		match.State = store.MatchStateActive
		snapshot = *match
		found = true
	}
	h.mu.Unlock()
	if !found {
		return
	}
	if err := h.store.SaveMatch(&snapshot); err != nil {
		log.Printf("hub: SaveMatch: %v", err)
	}
}

func (h *Hub) HandleRoleClaim(deviceID string, msg protocol.MatchRoleClaim) {
	if msg.Role != "host" {
		return
	}
	var assigned string
	var participants []string
	found := false
	h.mu.Lock()
	if match, ok := h.matches[msg.MatchID]; ok && contains(match.Participants, deviceID) {
		if match.HostDeviceID == "" {
			match.HostDeviceID = deviceID
		}
		assigned = match.HostDeviceID
		participants = append([]string(nil), match.Participants...)
		found = true
	}
	h.mu.Unlock()
	if !found {
		return
	}
	env, err := protocol.Encode("match.role_assigned", protocol.MatchRoleAssigned{
		MatchID: msg.MatchID, HostDeviceID: assigned,
	})
	if err != nil {
		log.Printf("hub: encode match.role_assigned: %v", err)
		return
	}
	h.sendToDevices(participants, env)
}

func (h *Hub) HandleSignal(fromDeviceID string, msg protocol.Signal) {
	var legitimate bool
	h.mu.Lock()
	if match, ok := h.matches[msg.MatchID]; ok {
		legitimate = contains(match.Participants, fromDeviceID) && contains(match.Participants, msg.ToDeviceID)
	}
	h.mu.Unlock()
	if !legitimate {
		return // not a real participant pair for this match
	}
	env, err := protocol.Encode("signal", protocol.SignalRelay{
		MatchID: msg.MatchID, FromDeviceID: fromDeviceID, Payload: msg.Payload,
	})
	if err != nil {
		log.Printf("hub: encode signal: %v", err)
		return
	}
	h.sendToDevices([]string{msg.ToDeviceID}, env)
}

func (h *Hub) endMatch(matchID, reason string) {
	var snapshot store.Match
	found := false
	h.mu.Lock()
	if match, ok := h.matches[matchID]; ok {
		match.State = store.MatchStateEnded
		snapshot = *match
		found = true
		delete(h.matches, matchID)
	}
	h.mu.Unlock()
	if !found {
		return
	}
	if err := h.store.SaveMatch(&snapshot); err != nil {
		log.Printf("hub: SaveMatch: %v", err)
	}
	env, err := protocol.Encode("match.cancelled", protocol.MatchEnded{MatchID: matchID, Reason: reason})
	if err != nil {
		log.Printf("hub: encode match.cancelled: %v", err)
		return
	}
	h.sendToDevices(snapshot.Participants, env)
}

// ---- Delivery / sweeping ----

func (h *Hub) sendToDevices(deviceIDs []string, env protocol.Envelope) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for _, id := range deviceIDs {
		live, ok := h.live[id]
		if !ok {
			continue
		}
		select {
		case live.conn.Send <- env:
		default:
			log.Printf("hub: send buffer full for device %s, dropping %s", id, env.Type)
		}
	}
}

func (h *Hub) sweepStale() {
	now := time.Now()
	var stale []string
	h.mu.Lock()
	for id, live := range h.live {
		if now.Sub(live.lastHeartbeat) > heartbeatTimeout {
			stale = append(stale, id)
			delete(h.live, id)
		}
	}
	h.mu.Unlock()
	for _, id := range stale {
		h.flipToWanted(id)
	}
}

// flipToWanted marks every game a now-stale device was actively "wants"-ing
// as "wanted" instead, and broadcasts the change to whoever else cares.
func (h *Hub) flipToWanted(deviceID string) {
	keys, err := h.store.GameKeysForDevice(deviceID)
	if err != nil {
		log.Printf("hub: GameKeysForDevice(%s): %v", deviceID, err)
		return
	}
	for _, key := range keys {
		records, err := h.store.RosterForGame(key)
		if err != nil {
			continue
		}
		for _, r := range records {
			if r.DeviceID != deviceID || r.State != "wants" {
				continue
			}
			r.State = "wanted"
			r.Since = time.Now().UTC()
			if err := h.store.UpsertRoster(r); err != nil {
				log.Printf("hub: UpsertRoster: %v", err)
			}
		}
		h.broadcastRoster(key)
	}
}

func contains(list []string, value string) bool {
	for _, v := range list {
		if v == value {
			return true
		}
	}
	return false
}
