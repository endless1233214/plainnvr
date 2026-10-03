package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/tls"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"strconv"
	"strings"
	"time"
)

const maxResponseBytes = 2 << 20

type protocolError struct {
	Code int
	Text string
}

func (err *protocolError) Error() string {
	if err.Text == "" {
		return fmt.Sprintf("camera returned error %d", err.Code)
	}
	return fmt.Sprintf("camera returned error %d: %s", err.Code, err.Text)
}

type cameraClient struct {
	host       string
	username   string
	password   string
	http       *http.Client
	secure     bool
	stok       string
	cnonce     string
	nonce      string
	hashedPass string
	key        []byte
	iv         []byte
	sequence   int
	tpap       bool
	tpapNonce  []byte
}

func validatedCameraAddress(host string) (string, error) {
	host = strings.TrimSpace(host)
	address, err := netip.ParseAddr(host)
	if err != nil {
		return "", errors.New("camera host must be an IP address")
	}
	address = address.Unmap()
	if !(address.IsPrivate() || address.IsLoopback() || address.IsLinkLocalUnicast()) {
		return "", errors.New("camera host must be a private or link-local IP address")
	}
	if address.IsUnspecified() || address.IsMulticast() {
		return "", errors.New("camera host is not a valid device target")
	}
	return address.String(), nil
}

func newCameraClient(host, username, password string, timeout time.Duration) (*cameraClient, error) {
	host, err := validatedCameraAddress(host)
	if err != nil {
		return nil, err
	}
	if username == "" || password == "" {
		return nil, errors.New("camera-local username and password are required")
	}
	dialer := &net.Dialer{Timeout: timeout}
	transport := &http.Transport{
		Proxy: nil,
		DialContext: func(ctx context.Context, network, _ string) (net.Conn, error) {
			return dialer.DialContext(ctx, network, net.JoinHostPort(host, "443"))
		},
		TLSClientConfig: &tls.Config{
			MinVersion:         tls.VersionTLS10,
			InsecureSkipVerify: true, // Device certificates are self-signed; the pinned IP is validated above.
			ServerName:         host,
		},
		DisableKeepAlives: true,
	}
	return &cameraClient{
		host: host, username: username, password: password,
		http: &http.Client{Timeout: timeout, Transport: transport},
	}, nil
}

func (client *cameraClient) post(path string, payload any, headers map[string]string) ([]byte, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	authority := net.JoinHostPort(client.host, "443")
	request, err := http.NewRequest(http.MethodPost, "https://"+authority+path, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	request.Host = authority
	request.Header.Set("Accept", "application/json")
	request.Header.Set("Content-Type", "application/json; charset=UTF-8")
	request.Header.Set("Connection", "close")
	request.Header.Set("Referer", "https://"+authority)
	request.Header.Set("User-Agent", "Tapo CameraClient Android")
	request.Header.Set("requestByApp", "true")
	for key, value := range headers {
		request.Header.Set(key, value)
	}
	response, err := client.http.Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	limited := io.LimitReader(response.Body, maxResponseBytes+1)
	data, err := io.ReadAll(limited)
	if err != nil {
		return nil, err
	}
	if len(data) > maxResponseBytes {
		return nil, errors.New("camera response exceeded limit")
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return nil, fmt.Errorf("camera returned HTTP %d", response.StatusCode)
	}
	return data, nil
}

func decodeObject(data []byte) (map[string]any, error) {
	var result map[string]any
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, errors.New("camera returned invalid JSON")
	}
	return result, nil
}

func errorCode(value map[string]any) int {
	number, _ := value["error_code"].(float64)
	return int(number)
}

func resultObject(value map[string]any) map[string]any {
	result, _ := value["result"].(map[string]any)
	return result
}

func (client *cameraClient) rawLogin(params map[string]any) (map[string]any, error) {
	data, err := client.post("/", map[string]any{"method": "login", "params": params}, nil)
	if err != nil {
		return nil, err
	}
	return decodeObject(data)
}

func (client *cameraClient) authenticate() error {
	probe, err := client.rawLogin(map[string]any{
		"encrypt_type": "3", "username": client.username,
	})
	if err != nil {
		return err
	}
	if errorCode(probe) == -40211 {
		client.tpap = true
		return client.authenticateTPAP()
	}
	data, _ := resultObject(probe)["data"].(map[string]any)
	if errorCode(probe) == -40413 && stringListContains(data["encrypt_type"], "3") {
		client.secure = true
		return client.authenticateSecure()
	}
	return client.authenticateLegacy()
}

func (client *cameraClient) postRaw(path, contentType string, body []byte) ([]byte, error) {
	authority := net.JoinHostPort(client.host, "443")
	request, err := http.NewRequest(http.MethodPost, "https://"+authority+path, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	request.Host = authority
	request.Header.Set("Accept", contentType)
	request.Header.Set("Content-Type", contentType)
	request.Header.Set("Referer", "https://"+authority)
	request.Header.Set("User-Agent", "Tapo CameraClient Android")
	request.Header.Set("requestByApp", "true")
	response, err := client.http.Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	data, err := io.ReadAll(io.LimitReader(response.Body, maxResponseBytes+1))
	if err != nil {
		return nil, err
	}
	if len(data) > maxResponseBytes {
		return nil, errors.New("camera response exceeded limit")
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return nil, fmt.Errorf("camera returned HTTP %d", response.StatusCode)
	}
	return data, nil
}

func (client *cameraClient) tpapLogin(params map[string]any) (map[string]any, error) {
	body, err := json.Marshal(map[string]any{"method": "login", "params": params})
	if err != nil {
		return nil, err
	}
	data, err := client.postRaw("/", "application/json", body)
	if err != nil {
		return nil, err
	}
	return decodeObject(data)
}

func (client *cameraClient) authenticateTPAP() error {
	discovery, _ := client.tpapLogin(map[string]any{"sub_method": "discover"})
	info, _ := resultObject(discovery)["tpap"].(map[string]any)
	username := lowerMD5("admin")
	if hashType, _ := info["user_hash_type"].(float64); int(hashType) == 1 {
		username = upperSHA256("admin")
	}
	passcodes := []string{lowerMD5(client.password), upperSHA256(client.password)}
	var lastErr error
	for _, passcode := range passcodes {
		// A pake_register result is single-use. A rejected pake_share consumes it,
		// so every passcode representation needs a fresh registration and random.
		userRandomBytes := make([]byte, 32)
		if _, err := rand.Read(userRandomBytes); err != nil {
			return err
		}
		userRandom := base64.StdEncoding.EncodeToString(userRandomBytes)
		register, err := client.tpapLogin(map[string]any{
			"sub_method": "pake_register", "username": username, "user_random": userRandom,
			"cipher_suites": []any{1}, "encryption": []any{"aes_128_ccm"}, "passcode_type": "userpw",
		})
		if err != nil {
			return err
		}
		if code := errorCode(register); code != 0 {
			return &protocolError{Code: code, Text: "TPAP registration failed"}
		}
		registerResult := resultObject(register)
		credential, err := applyExtraCrypt(passcode, registerResult["extra_crypt"])
		if err != nil {
			return err
		}
		spake, err := newSpakeClient(registerResult, userRandom, credential)
		if err != nil {
			return err
		}
		share, err := client.tpapLogin(map[string]any{
			"sub_method": "pake_share", "user_share": base64.StdEncoding.EncodeToString(spake.share),
			"user_confirm": base64.StdEncoding.EncodeToString(spake.userConfirm),
		})
		if err != nil {
			return err
		}
		if code := errorCode(share); code != 0 {
			if code == -40401 {
				lastErr = &protocolError{Code: code, Text: "TPAP password rejected"}
				continue
			}
			data := resultObject(share)
			if seconds, _ := data["sec_left"].(float64); seconds > 0 {
				return fmt.Errorf("camera login temporarily suspended for %d seconds", int(seconds))
			}
			return &protocolError{Code: code, Text: "TPAP login failed"}
		}
		shareResult := resultObject(share)
		encodedConfirm, _ := shareResult["dev_confirm"].(string)
		confirm, err := base64.StdEncoding.DecodeString(encodedConfirm)
		if err != nil || !spake.verifyDeviceConfirm(confirm) {
			return errors.New("TPAP device confirmation failed")
		}
		client.key, client.tpapNonce = spake.sessionKeyAndNonce()
		client.stok, _ = shareResult["stok"].(string)
		sequence, _ := shareResult["start_seq"].(float64)
		client.sequence = int(sequence)
		if client.stok == "" {
			return errors.New("TPAP login response did not include a session token")
		}
		return nil
	}
	if lastErr != nil {
		return lastErr
	}
	return errors.New("TPAP authentication failed")
}

func stringListContains(value any, wanted string) bool {
	items, _ := value.([]any)
	for _, item := range items {
		if text, _ := item.(string); text == wanted {
			return true
		}
	}
	return false
}

func (client *cameraClient) authenticateLegacy() error {
	reply, err := client.rawLogin(map[string]any{
		"hashed": true, "password": upperMD5(client.password), "username": client.username,
	})
	if err != nil {
		return err
	}
	if code := errorCode(reply); code != 0 {
		return &protocolError{Code: code, Text: "authentication failed"}
	}
	client.stok, _ = resultObject(reply)["stok"].(string)
	if client.stok == "" {
		return errors.New("camera login response did not include a session token")
	}
	return nil
}

func (client *cameraClient) authenticateSecure() error {
	cnonce, err := randomHex(4)
	if err != nil {
		return err
	}
	client.cnonce = cnonce
	first, err := client.rawLogin(map[string]any{
		"cnonce": cnonce, "encrypt_type": "3", "username": client.username,
	})
	if err != nil {
		return err
	}
	if code := errorCode(first); code != 0 {
		return &protocolError{Code: code, Text: "secure authentication challenge failed"}
	}
	data, _ := resultObject(first)["data"].(map[string]any)
	client.nonce, _ = data["nonce"].(string)
	confirm, _ := data["device_confirm"].(string)
	for _, candidate := range []string{upperSHA256(client.password), upperMD5(client.password)} {
		expected := upperSHA256(cnonce+candidate+client.nonce) + client.nonce + cnonce
		if confirm == expected {
			client.hashedPass = candidate
			break
		}
	}
	if client.hashedPass == "" {
		return errors.New("camera rejected the local password")
	}
	hashedKey := upperSHA256(cnonce + client.hashedPass + client.nonce)
	client.key = sha256Bytes("lsk" + cnonce + client.nonce + hashedKey)[:16]
	client.iv = sha256Bytes("ivb" + cnonce + client.nonce + hashedKey)[:16]
	digest := upperSHA256(client.hashedPass + cnonce + client.nonce)
	final, err := client.rawLogin(map[string]any{
		"cnonce": cnonce, "digest_passwd": digest + cnonce + client.nonce,
		"encrypt_type": "3", "username": client.username,
	})
	if err != nil {
		return err
	}
	if code := errorCode(final); code != 0 {
		return &protocolError{Code: code, Text: "secure authentication failed"}
	}
	result := resultObject(final)
	client.stok, _ = result["stok"].(string)
	sequence, _ := result["start_seq"].(float64)
	client.sequence = int(sequence)
	if client.stok == "" {
		return errors.New("camera login response did not include a session token")
	}
	return nil
}

func (client *cameraClient) execute(method string, params map[string]any) (map[string]any, error) {
	if client.stok == "" {
		if err := client.authenticate(); err != nil {
			return nil, err
		}
	}
	payload := map[string]any{
		"method": "multipleRequest",
		"params": map[string]any{"requests": []any{map[string]any{"method": method, "params": params}}},
	}
	var response map[string]any
	var err error
	if client.tpap {
		response, err = client.executeTPAP(payload)
	} else if client.secure {
		response, err = client.executeSecure(payload)
	} else {
		response, err = client.executePlain(payload)
	}
	if err != nil {
		return nil, err
	}
	result := resultObject(response)
	responses, _ := result["responses"].([]any)
	if len(responses) != 1 {
		return nil, errors.New("camera returned an unexpected response count")
	}
	inner, _ := responses[0].(map[string]any)
	if code := errorCode(inner); code != 0 {
		return nil, &protocolError{Code: code, Text: method + " is unsupported or failed"}
	}
	return resultObject(inner), nil
}

func (client *cameraClient) executeTPAP(payload map[string]any) (map[string]any, error) {
	plain, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	sequence := uint32(client.sequence)
	client.sequence++
	nonce := ccmNonce(client.tpapNonce, sequence)
	ciphertext, tag, err := ccmEncrypt(client.key, nonce, plain)
	if err != nil {
		return nil, err
	}
	body := make([]byte, 4, 4+len(ciphertext)+len(tag))
	binary.BigEndian.PutUint32(body, sequence)
	body = append(body, ciphertext...)
	body = append(body, tag...)
	data, err := client.postRaw("/stok="+client.stok+"/ds", "application/octet-stream", body)
	if err != nil {
		return nil, err
	}
	if len(data) > 0 && data[0] == '{' {
		response, parseErr := decodeObject(data)
		if parseErr != nil {
			return nil, parseErr
		}
		return nil, &protocolError{Code: errorCode(response), Text: "TPAP request refused"}
	}
	if len(data) < 20 {
		return nil, errors.New("camera returned a short TPAP response")
	}
	replySequence := binary.BigEndian.Uint32(data[:4])
	decrypted, err := ccmDecrypt(client.key, ccmNonce(client.tpapNonce, replySequence), data[4:len(data)-16], data[len(data)-16:])
	if err != nil {
		return nil, err
	}
	response, err := decodeObject(decrypted)
	if err != nil {
		return nil, err
	}
	if code := errorCode(response); code != 0 {
		return nil, &protocolError{Code: code}
	}
	return response, nil
}

func (client *cameraClient) executePlain(payload map[string]any) (map[string]any, error) {
	data, err := client.post("/stok="+client.stok+"/ds", payload, nil)
	if err != nil {
		return nil, err
	}
	response, err := decodeObject(data)
	if err != nil {
		return nil, err
	}
	if code := errorCode(response); code != 0 {
		return nil, &protocolError{Code: code}
	}
	return response, nil
}

func (client *cameraClient) executeSecure(payload map[string]any) (map[string]any, error) {
	plain, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	encrypted, err := encryptCBC(plain, client.key, client.iv)
	if err != nil {
		return nil, err
	}
	wrapper := map[string]any{
		"method": "securePassthrough",
		"params": map[string]any{"request": base64.StdEncoding.EncodeToString(encrypted)},
	}
	wrapperJSON, err := json.Marshal(wrapper)
	if err != nil {
		return nil, err
	}
	sequence := client.sequence
	tag1 := upperSHA256(client.hashedPass + client.cnonce)
	tag := upperSHA256(tag1 + string(wrapperJSON) + strconv.Itoa(sequence))
	client.sequence++
	data, err := client.post("/stok="+client.stok+"/ds", wrapper, map[string]string{
		"Seq": strconv.Itoa(sequence), "Tapo_tag": tag,
	})
	if err != nil {
		return nil, err
	}
	outer, err := decodeObject(data)
	if err != nil {
		return nil, err
	}
	if code := errorCode(outer); code != 0 {
		return nil, &protocolError{Code: code}
	}
	encoded, _ := resultObject(outer)["response"].(string)
	ciphertext, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil {
		return nil, errors.New("camera returned invalid encrypted data")
	}
	decrypted, err := decryptCBC(ciphertext, client.key, client.iv)
	if err != nil {
		return nil, err
	}
	response, err := decodeObject(decrypted)
	if err != nil {
		return nil, err
	}
	if code := errorCode(response); code != 0 {
		return nil, &protocolError{Code: code}
	}
	return response, nil
}
