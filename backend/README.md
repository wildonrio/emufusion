# Lucent Multiplayer Backend (alpha)

The self-hosted presence, matchmaking, and WebRTC-signaling service behind
Lucent's alpha multiplayer feature. It is intentionally small and does
exactly one job: help two (or more) devices find each other and exchange
a WebRTC handshake. It never sees, stores, or relays game input, video,
or audio -- once two devices are matched, gameplay traffic goes directly
peer-to-peer over a WebRTC DataChannel with no server in the loop.

See `docs/` (or the project plan this was built from) for the full
feature design. This file only covers running and deploying this piece.

## What it does

- **Presence**: one persistent WebSocket per device, with a heartbeat.
- **Roster**: per-game "wants to play" / "wanted to play" status, visible
  to every device that has ever expressed interest in that game.
- **Matchmaking**: instant matches when two online devices both want the
  same game right now, and scheduled matches when their submitted
  availability windows overlap.
- **Signaling relay**: forwards opaque WebRTC SDP/ICE payloads between
  exactly the two (or more) devices in a match. The payload is never
  parsed or interpreted here.

## Running locally

Requires Go 1.27+.

```sh
cd backend
go run ./cmd/lucent-multiplayer
```

Environment variables (both optional):

- `LUCENT_MULTIPLAYER_ADDR` -- listen address, default `:8787`.
- `LUCENT_MULTIPLAYER_DB` -- path to the bbolt database file, default
  `lucent-multiplayer.db` in the working directory.

Health check: `GET /healthz` returns `200 ok` once the server is ready.

## Tests

```sh
cd backend
go test ./... -race
```

`internal/hub`'s tests exercise the matching logic directly (instant
match, minPlayers gating, schedule overlap, participant validation).
`cmd/lucent-multiplayer`'s test exercises the real HTTP registration and
WebSocket auth flow end to end via `httptest`.

For a fuller, cross-implementation check (registration, roster,
matchmaking, and a **real** WebRTC handshake carried through the actual
signaling relay -- not a mock), see `testing/fake_peer.py`:

```sh
python3 -m venv backend/testing/.venv
backend/testing/.venv/bin/pip install -r backend/testing/requirements.txt
backend/testing/.venv/bin/python3 backend/testing/fake_peer.py
```

This script builds and runs the real backend as a subprocess against a
throwaway database, so it never touches a real deployment. It uses
`aiortc` for a genuine ICE/DTLS/DataChannel handshake rather than a mock,
specifically so a corrupted or mis-framed SDP/ICE relay would be caught
here rather than only surfacing later against a real Android client. Note:
the final "did the DataChannel actually open" step is a soft warning, not
a hard failure, if it can't complete within 20s -- see the comment beside
that check in the script for why (in short: this is sensitive to the
local machine's own network interface configuration in a way unrelated to
the backend's own correctness, which the SDP-relay assertions immediately
above it already verify).

## Deploying

This compiles to a single static binary with one small embedded
database file -- no separate database server, no container orchestration
required. Any of the following work:

- A small VPS (a $5/mo droplet-class instance is comfortably enough for a
  friends-and-family alpha).
- A free-tier PaaS with a persistent volume for the database file (Fly.io,
  Render).

```sh
cd backend
go build -o lucent-multiplayer ./cmd/lucent-multiplayer
# copy the binary + set LUCENT_MULTIPLAYER_ADDR/LUCENT_MULTIPLAYER_DB as needed
```

Put a TLS-terminating reverse proxy (Caddy, nginx, or the PaaS's own
edge) in front of it in any real deployment -- this binary itself only
speaks plain HTTP/WS.

### NAT traversal

The Android client uses free public STUN servers for ICE. This alpha
deliberately does **not** run a TURN relay: STUN alone lets the large
majority of consumer routers connect directly, and the minority behind
symmetric/carrier-grade NAT get a clear "couldn't connect directly"
message instead. Add a TURN relay later if real usage shows it's needed
-- unlike this signaling backend, TURN carries an ongoing bandwidth cost
proportional to actual playtime, so it's worth deferring until there's
real data on how often it's actually required.

## Wire protocol summary

One WebSocket per device: `GET /v1/connect`, headers `X-Device-Id` and
`Authorization: Bearer <secret>` (obtained once from `POST /v1/register`
with `{"nickname": "..."}`).

Client -> server message types: `heartbeat`, `want.set`,
`schedule.submit`, `schedule.cancel`, `invite.respond`,
`match.role_claim`, `signal`.

Server -> client message types: `identity.ack`, `roster.update`,
`match.scheduled`, `invite.available`, `match.role_assigned`, `signal`,
`match.cancelled`.

See `internal/protocol/messages.go` for the exact JSON shape of every
message, and `internal/hub/hub.go` for the matching logic that produces
them.
