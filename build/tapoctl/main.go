package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"time"
)

const version = "0.1.0"

func writeResult(value any) {
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetEscapeHTML(true)
	_ = encoder.Encode(value)
}

func fail(err error) {
	writeResult(map[string]any{"ok": false, "error": err.Error()})
	os.Exit(1)
}

func main() {
	if len(os.Args) == 2 && os.Args[1] == "--version" {
		fmt.Println("plainnvr-tapoctl " + version)
		return
	}
	decoder := json.NewDecoder(io.LimitReader(os.Stdin, 64<<10))
	decoder.UseNumber()
	var input request
	if err := decoder.Decode(&input); err != nil {
		fail(fmt.Errorf("invalid request: %w", err))
	}
	// Normalize json.Number values without accepting strings as numbers.
	if number, ok := input.Value.(json.Number); ok {
		value, err := number.Int64()
		if err != nil {
			fail(fmt.Errorf("invalid numeric value: %w", err))
		}
		input.Value = float64(value)
	}
	client, err := newCameraClient(input.Host, input.Username, input.Password, 8*time.Second)
	if err != nil {
		fail(err)
	}
	switch input.Operation {
	case "probe", "state":
		if err := client.authenticate(); err != nil {
			fail(err)
		}
		writeResult(probeCamera(client))
	case "set":
		if err := client.authenticate(); err != nil {
			fail(err)
		}
		result, err := setCameraControl(client, input.Control, input.Value)
		if err != nil {
			fail(err)
		}
		writeResult(map[string]any{"ok": true, "control": input.Control, "result": result})
	default:
		fail(fmt.Errorf("unsupported operation %q", input.Operation))
	}
}
