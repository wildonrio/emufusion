package store

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
)

// randomID produces a short, unguessable identifier prefixed with a kind
// tag purely for human readability in logs (e.g. "dev_3f9a...").
func randomID(kind string) string {
	buf := make([]byte, 16)
	if _, err := rand.Read(buf); err != nil {
		panic(fmt.Sprintf("randomID: system randomness unavailable: %v", err))
	}
	return kind + "_" + hex.EncodeToString(buf)
}

// NewSecret produces a high-entropy device secret (256 bits), returned to
// the device once at registration and never stored in plaintext.
func NewSecret() (string, error) {
	buf := make([]byte, 32)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return hex.EncodeToString(buf), nil
}
