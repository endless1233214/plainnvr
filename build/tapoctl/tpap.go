package main

import (
	"crypto/aes"
	"crypto/elliptic"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha1"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"math/big"
	"strings"
)

var (
	p256       = elliptic.P256()
	p256Order  = new(big.Int).Set(p256.Params().N)
	spakeM     = mustCompressedPoint("02886e2f97ace46e55ba9dd7242579f2993b64e16ef3dcab95afd497333d8fa12f")
	spakeN     = mustCompressedPoint("03d8bbd6c639c62937b04d997f38c3770719c629d7014d49a24b4f98baa1292b49")
	contextTag = []byte("PAKE V1")
)

type curvePoint struct{ x, y *big.Int }

func mustCompressedPoint(encoded string) curvePoint {
	data, err := hex.DecodeString(encoded)
	if err != nil {
		panic(err)
	}
	x, y := elliptic.UnmarshalCompressed(p256, data)
	if x == nil || y == nil {
		panic("invalid SPAKE2+ point")
	}
	return curvePoint{x, y}
}

func pointAdd(first, second curvePoint) curvePoint {
	x, y := p256.Add(first.x, first.y, second.x, second.y)
	return curvePoint{x, y}
}

func pointMultiply(scalar *big.Int, point curvePoint) curvePoint {
	x, y := p256.ScalarMult(point.x, point.y, scalar.Bytes())
	return curvePoint{x, y}
}

func pointBaseMultiply(scalar *big.Int) curvePoint {
	x, y := p256.ScalarBaseMult(scalar.Bytes())
	return curvePoint{x, y}
}

func pointNegate(point curvePoint) curvePoint {
	y := new(big.Int).Neg(point.y)
	y.Mod(y, p256.Params().P)
	return curvePoint{new(big.Int).Set(point.x), y}
}

func encodePoint(point curvePoint) []byte {
	return elliptic.Marshal(p256, point.x, point.y)
}

func decodePoint(encoded []byte) (curvePoint, error) {
	var x, y *big.Int
	if len(encoded) == 33 {
		x, y = elliptic.UnmarshalCompressed(p256, encoded)
	} else {
		x, y = elliptic.Unmarshal(p256, encoded)
	}
	if x == nil || y == nil {
		return curvePoint{}, errors.New("camera returned an invalid SPAKE2+ point")
	}
	return curvePoint{x, y}, nil
}

func hkdfSHA256(input, salt, info []byte, length int) []byte {
	if len(salt) == 0 {
		salt = make([]byte, sha256.Size)
	}
	extract := hmac.New(sha256.New, salt)
	extract.Write(input)
	key := extract.Sum(nil)
	result := make([]byte, 0, length)
	previous := []byte{}
	for counter := byte(1); len(result) < length; counter++ {
		expand := hmac.New(sha256.New, key)
		expand.Write(previous)
		expand.Write(info)
		expand.Write([]byte{counter})
		previous = expand.Sum(nil)
		result = append(result, previous...)
	}
	return result[:length]
}

func pbkdf2SHA256(password, salt []byte, iterations, length int) []byte {
	result := make([]byte, 0, length)
	for block := uint32(1); len(result) < length; block++ {
		mac := hmac.New(sha256.New, password)
		mac.Write(salt)
		var count [4]byte
		binary.BigEndian.PutUint32(count[:], block)
		mac.Write(count[:])
		u := mac.Sum(nil)
		t := append([]byte(nil), u...)
		for round := 1; round < iterations; round++ {
			mac = hmac.New(sha256.New, password)
			mac.Write(u)
			u = mac.Sum(nil)
			for index := range t {
				t[index] ^= u[index]
			}
		}
		result = append(result, t...)
	}
	return result[:length]
}

func lengthPrefixed(chunks ...[]byte) []byte {
	result := []byte{}
	for _, chunk := range chunks {
		var length [8]byte
		binary.LittleEndian.PutUint64(length[:], uint64(len(chunk)))
		result = append(result, length[:]...)
		result = append(result, chunk...)
	}
	return result
}

type spakeClient struct {
	share       []byte
	userConfirm []byte
	deviceKey   []byte
	sharedKey   []byte
}

func newSpakeClient(register map[string]any, userRandom, credential string) (*spakeClient, error) {
	randomScalar, err := rand.Int(rand.Reader, new(big.Int).Sub(p256Order, big.NewInt(1)))
	if err != nil {
		return nil, err
	}
	randomScalar.Add(randomScalar, big.NewInt(1))
	return newSpakeClientWithScalar(register, userRandom, credential, randomScalar)
}

func newSpakeClientWithScalar(register map[string]any, userRandom, credential string, randomScalar *big.Int) (*spakeClient, error) {
	decode := func(key string) ([]byte, error) {
		value, _ := register[key].(string)
		decoded, err := base64.StdEncoding.DecodeString(value)
		if err != nil || len(decoded) == 0 {
			return nil, fmt.Errorf("camera returned invalid %s", key)
		}
		return decoded, nil
	}
	deviceSalt, err := decode("dev_salt")
	if err != nil {
		return nil, err
	}
	deviceShare, err := decode("dev_share")
	if err != nil {
		return nil, err
	}
	deviceRandom, err := decode("dev_random")
	if err != nil {
		return nil, err
	}
	iterationsFloat, _ := register["iterations"].(float64)
	iterations := int(iterationsFloat)
	if iterations < 1 || iterations > 10_000_000 {
		return nil, errors.New("camera returned invalid SPAKE2+ iteration count")
	}
	derived := pbkdf2SHA256([]byte(credential), deviceSalt, iterations, 80)
	w0 := new(big.Int).SetBytes(derived[:40])
	w0.Mod(w0, p256Order)
	w1 := new(big.Int).SetBytes(derived[40:])
	w1.Mod(w1, p256Order)
	yPoint, err := decodePoint(deviceShare)
	if err != nil {
		return nil, err
	}
	if randomScalar == nil || randomScalar.Sign() <= 0 || randomScalar.Cmp(p256Order) >= 0 {
		return nil, errors.New("invalid local SPAKE2+ scalar")
	}
	xPoint := pointAdd(pointBaseMultiply(randomScalar), pointMultiply(w0, spakeM))
	hPoint := pointAdd(yPoint, pointNegate(pointMultiply(w0, spakeN)))
	xEncoded := encodePoint(xPoint)
	yEncoded := encodePoint(yPoint)
	userRandomBytes, err := base64.StdEncoding.DecodeString(userRandom)
	if err != nil {
		return nil, errors.New("invalid local SPAKE2+ random value")
	}
	contextHash := sha256.Sum256(append(append(append([]byte{}, contextTag...), userRandomBytes...), deviceRandom...))
	transcript := lengthPrefixed(
		contextHash[:], []byte{}, []byte{}, encodePoint(spakeM), encodePoint(spakeN),
		xEncoded, yEncoded, encodePoint(pointMultiply(randomScalar, hPoint)),
		encodePoint(pointMultiply(w1, hPoint)), paddedScalar(w0),
	)
	keyExchange := sha256.Sum256(transcript)
	confirmKeys := hkdfSHA256(keyExchange[:], nil, []byte("ConfirmationKeys"), 64)
	userMAC := hmac.New(sha256.New, confirmKeys[:32])
	userMAC.Write(yEncoded)
	shared := hkdfSHA256(keyExchange[:], nil, []byte("SharedKey"), 32)
	return &spakeClient{share: xEncoded, userConfirm: userMAC.Sum(nil), deviceKey: confirmKeys[32:], sharedKey: shared}, nil
}

func paddedScalar(value *big.Int) []byte {
	result := make([]byte, 32)
	value.FillBytes(result)
	return result
}

func (client *spakeClient) verifyDeviceConfirm(confirm []byte) bool {
	mac := hmac.New(sha256.New, client.deviceKey)
	mac.Write(client.share)
	return hmac.Equal(mac.Sum(nil), confirm)
}

func (client *spakeClient) sessionKeyAndNonce() ([]byte, []byte) {
	key := hkdfSHA256(client.sharedKey, []byte("tp-kdf-salt-aes128-key"), []byte("tp-kdf-info-aes128-key"), 32)[:16]
	nonce := hkdfSHA256(client.sharedKey, []byte("tp-kdf-salt-aes128-iv"), []byte("tp-kdf-info-aes128-iv"), 32)[:12]
	return key, nonce
}

func lowerMD5(value string) string { return strings.ToLower(upperMD5(value)) }

func lowerSHA1(value string) string {
	sum := sha1.Sum([]byte(value))
	return hex.EncodeToString(sum[:])
}

const cryptAlphabet = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

var cryptOrder = [][3]int{{0, 10, 20}, {21, 1, 11}, {12, 22, 2}, {3, 13, 23}, {24, 4, 14}, {15, 25, 5}, {6, 16, 26}, {27, 7, 17}, {18, 28, 8}, {9, 19, 29}}

func cryptTo64(value uint32, length int) string {
	var builder strings.Builder
	for count := 0; count < length; count++ {
		builder.WriteByte(cryptAlphabet[value&0x3f])
		value >>= 6
	}
	return builder.String()
}

func repeated(value []byte, length int) []byte {
	result := make([]byte, 0, length)
	for len(result) < length {
		result = append(result, value...)
	}
	return result[:length]
}

func sha256Crypt(key, prefix string) (string, error) {
	rest := prefix
	if strings.HasPrefix(rest, "$5$") {
		rest = rest[3:]
	}
	rounds, explicit := 5000, false
	if strings.HasPrefix(rest, "rounds=") {
		head, tail, found := strings.Cut(rest, "$")
		if found {
			var parsed int
			if _, err := fmt.Sscanf(head, "rounds=%d", &parsed); err != nil {
				return "", errors.New("invalid password-shadow rounds")
			}
			if parsed < 1000 {
				parsed = 1000
			}
			if parsed > 999999999 {
				parsed = 999999999
			}
			rounds, explicit, rest = parsed, true, tail
		}
	}
	salt := rest
	if index := strings.IndexByte(salt, '$'); index >= 0 {
		salt = salt[:index]
	}
	if len(salt) > 16 {
		salt = salt[:16]
	}
	k, s := []byte(key), []byte(salt)
	bHash := sha256.Sum256(append(append(append([]byte{}, k...), s...), k...))
	a := sha256.New()
	a.Write(k)
	a.Write(s)
	a.Write(repeated(bHash[:], len(k)))
	for count := len(k); count > 0; count >>= 1 {
		if count&1 == 1 {
			a.Write(bHash[:])
		} else {
			a.Write(k)
		}
	}
	c := a.Sum(nil)
	pHash := sha256.Sum256(bytesRepeat(k, len(k)))
	p := repeated(pHash[:], len(k))
	sHash := sha256.Sum256(bytesRepeat(s, 16+int(c[0])))
	sb := repeated(sHash[:], len(s))
	for index := 0; index < rounds; index++ {
		hash := sha256.New()
		if index&1 == 1 {
			hash.Write(p)
		} else {
			hash.Write(c)
		}
		if index%3 != 0 {
			hash.Write(sb)
		}
		if index%7 != 0 {
			hash.Write(p)
		}
		if index&1 == 1 {
			hash.Write(c)
		} else {
			hash.Write(p)
		}
		c = hash.Sum(nil)
	}
	var builder strings.Builder
	for _, order := range cryptOrder {
		value := uint32(c[order[0]])<<16 | uint32(c[order[1]])<<8 | uint32(c[order[2]])
		builder.WriteString(cryptTo64(value, 4))
	}
	builder.WriteString(cryptTo64(uint32(c[31])<<8|uint32(c[30]), 3))
	roundsPart := ""
	if explicit {
		roundsPart = fmt.Sprintf("rounds=%d$", rounds)
	}
	return "$5$" + roundsPart + salt + "$" + builder.String(), nil
}

func bytesRepeat(value []byte, count int) []byte {
	result := make([]byte, 0, len(value)*count)
	for index := 0; index < count; index++ {
		result = append(result, value...)
	}
	return result
}

func applyExtraCrypt(passcode string, extra any) (string, error) {
	config, ok := extra.(map[string]any)
	if !ok || len(config) == 0 {
		return passcode, nil
	}
	kind, _ := config["type"].(string)
	params, _ := config["params"].(map[string]any)
	if strings.ToLower(kind) != "password_shadow" {
		return "", fmt.Errorf("unsupported TPAP credential transform %q", kind)
	}
	idFloat, _ := params["passwd_id"].(float64)
	switch int(idFloat) {
	case 5:
		prefix, _ := params["passwd_prefix"].(string)
		return sha256Crypt(passcode, prefix)
	case 2:
		return lowerSHA1(passcode), nil
	default:
		return "", fmt.Errorf("unsupported password-shadow id %d", int(idFloat))
	}
}

func ccmNonce(base []byte, sequence uint32) []byte {
	nonce := make([]byte, 12)
	copy(nonce, base)
	binary.BigEndian.PutUint32(nonce[8:], sequence)
	return nonce
}

func ccmEncrypt(key, nonce, plain []byte) ([]byte, []byte, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, nil, err
	}
	if len(nonce) != 12 || len(plain) >= 1<<24 {
		return nil, nil, errors.New("invalid CCM input")
	}
	mac := ccmMAC(block, nonce, plain)
	ciphertext := make([]byte, len(plain))
	s0 := ccmCounterBlock(block, nonce, 0)
	for offset, counter := 0, uint32(1); offset < len(plain); offset, counter = offset+16, counter+1 {
		stream := ccmCounterBlock(block, nonce, counter)
		end := offset + 16
		if end > len(plain) {
			end = len(plain)
		}
		for index := offset; index < end; index++ {
			ciphertext[index] = plain[index] ^ stream[index-offset]
		}
	}
	tag := make([]byte, 16)
	for index := range tag {
		tag[index] = mac[index] ^ s0[index]
	}
	return ciphertext, tag, nil
}

func ccmDecrypt(key, nonce, ciphertext, tag []byte) ([]byte, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	if len(nonce) != 12 || len(tag) != 16 {
		return nil, errors.New("invalid CCM response")
	}
	plain := make([]byte, len(ciphertext))
	for offset, counter := 0, uint32(1); offset < len(ciphertext); offset, counter = offset+16, counter+1 {
		stream := ccmCounterBlock(block, nonce, counter)
		end := offset + 16
		if end > len(ciphertext) {
			end = len(ciphertext)
		}
		for index := offset; index < end; index++ {
			plain[index] = ciphertext[index] ^ stream[index-offset]
		}
	}
	mac := ccmMAC(block, nonce, plain)
	s0 := ccmCounterBlock(block, nonce, 0)
	expected := make([]byte, 16)
	for index := range expected {
		expected[index] = mac[index] ^ s0[index]
	}
	if subtle.ConstantTimeCompare(expected, tag) != 1 {
		return nil, errors.New("camera response failed CCM authentication")
	}
	return plain, nil
}

func ccmMAC(block cipherBlock, nonce, plain []byte) []byte {
	first := make([]byte, 16)
	first[0] = 0x3a
	copy(first[1:13], nonce)
	first[13] = byte(len(plain) >> 16)
	first[14] = byte(len(plain) >> 8)
	first[15] = byte(len(plain))
	state := make([]byte, 16)
	ccmMACBlock(block, state, first)
	for offset := 0; offset < len(plain); offset += 16 {
		chunk := make([]byte, 16)
		end := offset + 16
		if end > len(plain) {
			end = len(plain)
		}
		copy(chunk, plain[offset:end])
		ccmMACBlock(block, state, chunk)
	}
	return state
}

type cipherBlock interface{ Encrypt(dst, src []byte) }

func ccmMACBlock(block cipherBlock, state, value []byte) {
	for index := 0; index < 16; index++ {
		state[index] ^= value[index]
	}
	block.Encrypt(state, state)
}

func ccmCounterBlock(block cipherBlock, nonce []byte, counter uint32) []byte {
	input := make([]byte, 16)
	input[0] = 2
	copy(input[1:13], nonce)
	input[13] = byte(counter >> 16)
	input[14] = byte(counter >> 8)
	input[15] = byte(counter)
	output := make([]byte, 16)
	block.Encrypt(output, input)
	return output
}
