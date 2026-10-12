package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"github.com/emufusion/multiplayer-backend/internal/hub"
	"github.com/emufusion/multiplayer-backend/internal/protocol"
	"github.com/emufusion/multiplayer-backend/internal/store"
)

// TestRegisterAndConnectEndToEnd exercises the real HTTP surface a device
// actually calls: register once to obtain credentials, then open the
// authenticated WebSocket and confirm the server greets it with
// identity.ack. Unlike hub_test.go (which calls Hub methods directly),
// this is what would catch a routing, header-parsing, or auth mistake in
// main.go itself.
func TestRegisterAndConnectEndToEnd(t *testing.T) {
	db, err := store.Open(filepath.Join(t.TempDir(), "test.db"))
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { db.Close() })
	h := hub.New(db)
	stop := make(chan struct{})
	go h.Run(stop)
	t.Cleanup(func() { close(stop) })

	server := httptest.NewServer(newMux(db, h))
	t.Cleanup(server.Close)

	registerBody, _ := json.Marshal(registerRequest{Nickname: "Alice"})
	resp, err := http.Post(server.URL+"/v1/register", "application/json", bytes.NewReader(registerBody))
	if err != nil {
		t.Fatalf("register: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("register: expected 200, got %d", resp.StatusCode)
	}
	var reg registerResponse
	if err := json.NewDecoder(resp.Body).Decode(&reg); err != nil {
		t.Fatalf("decode register response: %v", err)
	}
	if reg.DeviceID == "" || reg.Secret == "" {
		t.Fatalf("expected a non-empty deviceId and secret, got %+v", reg)
	}

	// A wrong secret must be rejected.
	badHeader := http.Header{}
	badHeader.Set("X-Device-Id", reg.DeviceID)
	badHeader.Set("Authorization", "Bearer wrong-secret")
	wsURL := "ws" + strings.TrimPrefix(server.URL, "http") + "/v1/connect"
	if _, resp, err := websocket.DefaultDialer.Dial(wsURL, badHeader); err == nil {
		t.Fatalf("expected the wrong secret to be rejected")
	} else if resp == nil || resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401 for a bad secret, got %+v (err=%v)", resp, err)
	}

	goodHeader := http.Header{}
	goodHeader.Set("X-Device-Id", reg.DeviceID)
	goodHeader.Set("Authorization", "Bearer "+reg.Secret)
	conn, resp, err := websocket.DefaultDialer.Dial(wsURL, goodHeader)
	if err != nil {
		t.Fatalf("connect with correct credentials: %v (status=%v)", err, resp)
	}
	defer conn.Close()

	conn.SetReadDeadline(time.Now().Add(2 * time.Second))
	var env protocol.Envelope
	if err := conn.ReadJSON(&env); err != nil {
		t.Fatalf("read identity.ack: %v", err)
	}
	if env.Type != "identity.ack" {
		t.Fatalf("expected identity.ack as the first message, got %q", env.Type)
	}
	var ack protocol.IdentityAck
	if err := json.Unmarshal(env.Payload, &ack); err != nil {
		t.Fatalf("decode identity.ack: %v", err)
	}
	if ack.DeviceID != reg.DeviceID || ack.Nickname != "Alice" {
		t.Fatalf("unexpected identity.ack: %+v", ack)
	}
}
