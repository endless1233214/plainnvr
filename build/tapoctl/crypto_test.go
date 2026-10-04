package main

import (
	"bytes"
	"encoding/base64"
	"encoding/hex"
	"math/big"
	"testing"
)

func TestCBCAndPaddingRoundTrip(t *testing.T) {
	key := []byte("0123456789abcdef")
	iv := []byte("fedcba9876543210")
	for _, input := range [][]byte{[]byte("a"), []byte("sixteen-bytes!!!"), bytes.Repeat([]byte("x"), 127)} {
		encrypted, err := encryptCBC(input, key, iv)
		if err != nil {
			t.Fatal(err)
		}
		plain, err := decryptCBC(encrypted, key, iv)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(input, plain) {
			t.Fatalf("round trip mismatch: %q", plain)
		}
	}
}

func TestValidatedCameraAddress(t *testing.T) {
	for _, value := range []string{"192.168.1.20", "10.2.3.4", "127.0.0.1", "fe80::1"} {
		if _, err := validatedCameraAddress(value); err != nil {
			t.Errorf("%s: %v", value, err)
		}
	}
	for _, value := range []string{"example.com", "8.8.8.8", "0.0.0.0", "224.0.0.1"} {
		if _, err := validatedCameraAddress(value); err == nil {
			t.Errorf("expected %s to be rejected", value)
		}
	}
}

func TestSHA256CryptPublishedVectors(t *testing.T) {
	tests := []struct {
		key, prefix, expected string
	}{
		{
			"Hello world!",
			"$5$saltstring",
			"$5$saltstring$5B8vYYiY.CVt1RlTTf8KbXBH3hsxY/GNooZaBBGWEc5",
		},
		{
			"Hello world!",
			"$5$rounds=10000$saltstringsaltstring",
			"$5$rounds=10000$saltstringsaltst$3xv.VbSHBb41AL9AvLeujZkZRBAwqFMz2.opqey6IcA",
		},
	}
	for _, test := range tests {
		actual, err := sha256Crypt(test.key, test.prefix)
		if err != nil {
			t.Fatal(err)
		}
		if actual != test.expected {
			t.Fatalf("sha256-crypt mismatch: %q", actual)
		}
	}
}

func TestCCMMatchesIndependentVector(t *testing.T) {
	decode := func(value string) []byte {
		result, err := hex.DecodeString(value)
		if err != nil {
			t.Fatal(err)
		}
		return result
	}
	key := decode("000102030405060708090a0b0c0d0e0f")
	nonce := decode("101112131415161718191a1b")
	plain := decode("202122232425262728292a2b2c2d2e2f3031323334353637")
	wantCiphertext := decode("03949b8366d10b95228555eb5849f5a94b86e08401723c1c")
	wantTag := decode("e67133d1195de9839f83f14684e92314")

	ciphertext, tag, err := ccmEncrypt(key, nonce, plain)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(ciphertext, wantCiphertext) || !bytes.Equal(tag, wantTag) {
		t.Fatalf("CCM vector mismatch: %x %x", ciphertext, tag)
	}
	decrypted, err := ccmDecrypt(key, nonce, ciphertext, tag)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(decrypted, plain) {
		t.Fatal("CCM decryption mismatch")
	}
	tag[0] ^= 1
	if _, err := ccmDecrypt(key, nonce, ciphertext, tag); err == nil {
		t.Fatal("tampered CCM tag was accepted")
	}
}

func TestSpakeClientMatchesPyTapoVector(t *testing.T) {
	register := map[string]any{
		"dev_salt":   "AAECAwQFBgcICQoLDA0ODw==",
		"dev_share":  "BP/EtsmAHGmSz53flPtbZMBWccJqRlV6wJoNFJONlF/ovKofxftWCA/KAHTqFCFhAO1mCA9nYlA/pBKBgWQWpKs=",
		"dev_random": "QEFCQ0RFRkdISUpLTE1OT1BRUlNUVVZXWFlaW1xdXl8=",
		"iterations": float64(17),
	}
	scalar, ok := new(big.Int).SetString("abcdef123456789abcdef123456789abcdef123456789abcdef12345678a", 16)
	if !ok {
		t.Fatal("invalid test scalar")
	}
	client, err := newSpakeClientWithScalar(
		register,
		"ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8=",
		"fixed-test-credential",
		scalar,
	)
	if err != nil {
		t.Fatal(err)
	}
	wantShare, _ := hex.DecodeString("04c3f556ceea14f4bedc93d1e25290d74218418615c6e913256da268ec3f5166f4d4e1792dee6dec93882e3696594c6afb76f3af4986f6e2c9236d711d582233a7")
	wantConfirm, _ := hex.DecodeString("5ad3920ce585291bedde1be0cd7209dfa2e507a40e570a015a83e7fd6597bba6")
	deviceConfirm, _ := hex.DecodeString("30a134235f421b834ec177e4ec298acf1eecc94353a6ef004cb073eb43f55ede")
	if !bytes.Equal(client.share, wantShare) {
		t.Fatalf("SPAKE2+ share mismatch: %x", client.share)
	}
	if !bytes.Equal(client.userConfirm, wantConfirm) {
		t.Fatalf("SPAKE2+ confirmation mismatch: %x", client.userConfirm)
	}
	if !client.verifyDeviceConfirm(deviceConfirm) {
		t.Fatal("SPAKE2+ device confirmation failed")
	}
	key, nonce := client.sessionKeyAndNonce()
	if hex.EncodeToString(key) != "0db5e236e0b7e0a6b8b33984d59199f7" {
		t.Fatalf("SPAKE2+ session key mismatch: %x", key)
	}
	if base64.StdEncoding.EncodeToString(nonce) != "q7T7hGSRa/g/s7Ss" {
		t.Fatalf("SPAKE2+ nonce mismatch: %x", nonce)
	}
}
