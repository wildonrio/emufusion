// Command lucent-multiplayer is the self-hosted presence, matchmaking,
// and WebRTC-signaling backend for Lucent's alpha multiplayer feature. It
// deliberately never carries game input, video, or audio -- only small,
// infrequent presence/roster/schedule/handshake messages. Actual gameplay
// traffic between matched devices goes directly peer-to-peer over a
// WebRTC DataChannel once this service has introduced them.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/gorilla/websocket"
	"github.com/pegasus-lucent/multiplayer-backend/internal/hub"
	"github.com/pegasus-lucent/multiplayer-backend/internal/protocol"
	"github.com/pegasus-lucent/multiplayer-backend/internal/store"
)

func main() {
	dbPath := envOr("LUCENT_MULTIPLAYER_DB", "lucent-multiplayer.db")
	addr := envOr("LUCENT_MULTIPLAYER_ADDR", ":8787")

	db, err := store.Open(dbPath)
	if err != nil {
		log.Fatalf("open store: %v", err)
	}
	defer db.Close()

	h := hub.New(db)
	stop := make(chan struct{})
	go h.Run(stop)
	defer close(stop)

	server := &http.Server{Addr: addr, Handler: newMux(db, h), ReadHeaderTimeout: 5 * time.Second}
	go func() {
		log.Printf("lucent-multiplayer listening on %s (db=%s)", addr, dbPath)
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("serve: %v", err)
		}
	}()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	<-sigCh
	log.Print("shutting down")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = server.Shutdown(ctx)
}

// newMux is factored out of main() so tests can exercise the real HTTP
// routing (registration, then an authenticated WebSocket upgrade) against
// an httptest.Server instead of only unit-testing the hub in isolation.
func newMux(db *store.Store, h *hub.Hub) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/register", handleRegister(db))
	mux.HandleFunc("/v1/connect", handleConnect(db, h))
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	return mux
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// ---- Registration ----

type registerRequest struct {
	Nickname string `json:"nickname"`
}

type registerResponse struct {
	DeviceID string `json:"deviceId"`
	Secret   string `json:"secret"`
	Nickname string `json:"nickname"`
}

// handleRegister is called exactly once per device, the first time the
// app runs. It hands back a device ID and a secret; the client persists
// both locally (see DeviceIdentity on the Android side) and never
// registers again.
func handleRegister(db *store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST required", http.StatusMethodNotAllowed)
			return
		}
		var req registerRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "invalid JSON body", http.StatusBadRequest)
			return
		}
		nickname := strings.TrimSpace(req.Nickname)
		if nickname == "" {
			nickname = "Player"
		}
		if len(nickname) > 40 {
			nickname = nickname[:40]
		}
		secret, err := store.NewSecret()
		if err != nil {
			http.Error(w, "could not generate secret", http.StatusInternalServerError)
			return
		}
		device, err := db.CreateDevice(nickname, secret)
		if err != nil {
			http.Error(w, "could not create device", http.StatusInternalServerError)
			return
		}
		writeJSON(w, http.StatusOK, registerResponse{DeviceID: device.ID, Secret: secret, Nickname: nickname})
	}
}

// ---- WebSocket connect ----

var upgrader = websocket.Upgrader{
	ReadBufferSize:  4096,
	WriteBufferSize: 4096,
	// This backend is meant to be reached only by the Lucent app itself
	// (over TLS, in front of a reverse proxy in production); it is not a
	// browser-facing API, so a permissive origin check is appropriate
	// here rather than a browser CORS-style allowlist.
	CheckOrigin: func(r *http.Request) bool { return true },
}

func handleConnect(db *store.Store, h *hub.Hub) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		deviceID := r.Header.Get("X-Device-Id")
		secret := bearerToken(r.Header.Get("Authorization"))
		if deviceID == "" || secret == "" {
			http.Error(w, "X-Device-Id and Authorization: Bearer <secret> are required", http.StatusUnauthorized)
			return
		}
		device, found, err := db.GetDevice(deviceID)
		if err != nil {
			http.Error(w, "lookup failed", http.StatusInternalServerError)
			return
		}
		if !found || !store.VerifySecret(device, secret) {
			http.Error(w, "invalid device credentials", http.StatusUnauthorized)
			return
		}

		if nickname := strings.TrimSpace(r.URL.Query().Get("nickname")); nickname != "" && nickname != device.Nickname {
			if len(nickname) > 40 {
				nickname = nickname[:40]
			}
			if err := db.SetNickname(deviceID, nickname); err == nil {
				device.Nickname = nickname
			}
		}

		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			log.Printf("connect: upgrade failed for %s: %v", deviceID, err)
			return
		}
		session := h.Connect(deviceID, device.Nickname)
		defer h.Disconnect(deviceID)
		runSession(conn, session, h)
	}
}

func bearerToken(header string) string {
	const prefix = "Bearer "
	if !strings.HasPrefix(header, prefix) {
		return ""
	}
	return strings.TrimPrefix(header, prefix)
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

// runSession pumps one connected device's WebSocket in both directions
// until it closes. It is intentionally simple (two goroutines, one
// channel) rather than a generic multiplexed pipeline, since each device
// has exactly one connection to this backend at a time.
func runSession(conn *websocket.Conn, session *hub.Connection, h *hub.Hub) {
	defer conn.Close()

	ack, err := protocol.Encode("identity.ack", protocol.IdentityAck{
		DeviceID: session.DeviceID, Nickname: session.Nickname,
	})
	if err == nil {
		_ = conn.WriteJSON(ack)
	}

	done := make(chan struct{})
	go func() {
		defer close(done)
		for env := range session.Send {
			conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if err := conn.WriteJSON(env); err != nil {
				return
			}
		}
	}()

	for {
		var env protocol.Envelope
		if err := conn.ReadJSON(&env); err != nil {
			break
		}
		dispatch(h, session.DeviceID, env)
	}
	<-done
}

func dispatch(h *hub.Hub, deviceID string, env protocol.Envelope) {
	switch env.Type {
	case "heartbeat":
		h.HandleHeartbeat(deviceID)
	case "want.set":
		var msg protocol.WantSet
		if unmarshal(env.Payload, &msg) {
			h.HandleWantSet(deviceID, "", msg)
		}
	case "schedule.submit":
		var msg protocol.ScheduleSubmit
		if unmarshal(env.Payload, &msg) {
			h.HandleScheduleSubmit(deviceID, msg)
		}
	case "schedule.cancel":
		var msg protocol.ScheduleCancel
		if unmarshal(env.Payload, &msg) {
			h.HandleScheduleCancel(deviceID, msg.ScheduleID)
		}
	case "invite.respond":
		var msg protocol.InviteRespond
		if unmarshal(env.Payload, &msg) {
			h.HandleInviteRespond(deviceID, msg)
		}
	case "match.role_claim":
		var msg protocol.MatchRoleClaim
		if unmarshal(env.Payload, &msg) {
			h.HandleRoleClaim(deviceID, msg)
		}
	case "signal":
		var msg protocol.Signal
		if unmarshal(env.Payload, &msg) {
			h.HandleSignal(deviceID, msg)
		}
	default:
		log.Printf("dispatch: unknown message type %q from %s", env.Type, deviceID)
	}
}

func unmarshal(raw json.RawMessage, target any) bool {
	if err := json.Unmarshal(raw, target); err != nil {
		log.Printf("dispatch: bad payload: %v", err)
		return false
	}
	return true
}
