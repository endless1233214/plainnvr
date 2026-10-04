package main

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/md5"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strings"
)

func upperMD5(value string) string {
	sum := md5.Sum([]byte(value))
	return strings.ToUpper(hex.EncodeToString(sum[:]))
}

func upperSHA256(value string) string {
	sum := sha256.Sum256([]byte(value))
	return strings.ToUpper(hex.EncodeToString(sum[:]))
}

func sha256Bytes(value string) []byte {
	sum := sha256.Sum256([]byte(value))
	return sum[:]
}

func randomHex(bytesCount int) (string, error) {
	value := make([]byte, bytesCount)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return strings.ToUpper(hex.EncodeToString(value)), nil
}

func padPKCS7(value []byte, blockSize int) []byte {
	padding := blockSize - len(value)%blockSize
	return append(value, bytes.Repeat([]byte{byte(padding)}, padding)...)
}

func unpadPKCS7(value []byte, blockSize int) ([]byte, error) {
	if len(value) == 0 || len(value)%blockSize != 0 {
		return nil, errors.New("invalid encrypted response length")
	}
	padding := int(value[len(value)-1])
	if padding == 0 || padding > blockSize || padding > len(value) {
		return nil, errors.New("invalid encrypted response padding")
	}
	for _, item := range value[len(value)-padding:] {
		if int(item) != padding {
			return nil, errors.New("invalid encrypted response padding")
		}
	}
	return value[:len(value)-padding], nil
}

func encryptCBC(value, key, iv []byte) ([]byte, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	value = padPKCS7(value, aes.BlockSize)
	result := make([]byte, len(value))
	cipher.NewCBCEncrypter(block, iv).CryptBlocks(result, value)
	return result, nil
}

func decryptCBC(value, key, iv []byte) ([]byte, error) {
	if len(value) == 0 || len(value)%aes.BlockSize != 0 {
		return nil, errors.New("invalid encrypted response length")
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	result := make([]byte, len(value))
	cipher.NewCBCDecrypter(block, iv).CryptBlocks(result, value)
	return unpadPKCS7(result, aes.BlockSize)
}
