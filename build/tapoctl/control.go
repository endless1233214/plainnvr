package main

import (
	"errors"
	"fmt"
	"strings"
)

type request struct {
	Host      string `json:"host"`
	Username  string `json:"username"`
	Password  string `json:"password"`
	Operation string `json:"operation"`
	Control   string `json:"control,omitempty"`
	Value     any    `json:"value,omitempty"`
}

type probeSpec struct {
	Name   string
	Method string
	Params map[string]any
}

var probes = []probeSpec{
	{"device", "getDeviceInfo", map[string]any{"device_info": map[string]any{"name": []any{"basic_info"}}}},
	{"privacy", "getLensMaskConfig", map[string]any{"lens_mask": map[string]any{"name": []any{"lens_mask_info"}}}},
	{"led", "getLedStatus", map[string]any{"led": map[string]any{"name": []any{"config"}}}},
	{"spotlight", "getWhitelampConfig", map[string]any{"image": map[string]any{"name": []any{"switch"}}}},
	{"spotlight_status", "getWhitelampStatus", map[string]any{"image": map[string]any{"get_wtl_status": []any{"null"}}}},
	{"night_vision", "getNightVisionCapability", map[string]any{"image_capability": map[string]any{"name": []any{"supplement_lamp"}}}},
	{"alarm", "getAlarmConfig", map[string]any{"msg_alarm": map[string]any{}}},
	{"audio", "getAudioConfig", map[string]any{"audio_config": map[string]any{"name": []any{"speaker", "microphone", "record_audio"}}}},
	{"motion", "getDetectionConfig", map[string]any{"motion_detection": map[string]any{"name": []any{"motion_det"}}}},
	{"person", "getPersonDetectionConfig", map[string]any{"people_detection": map[string]any{"name": []any{"detection"}}}},
}

func probeCamera(client *cameraClient) map[string]any {
	capabilities := map[string]bool{}
	state := map[string]any{}
	errorsByFeature := map[string]string{}
	for _, probe := range probes {
		result, err := client.execute(probe.Method, probe.Params)
		if err != nil {
			errorsByFeature[probe.Name] = err.Error()
			continue
		}
		capabilities[probe.Name] = true
		state[probe.Name] = result
	}
	return map[string]any{
		"ok": true, "driver": "tapo_local", "transport": transportName(client),
		"capabilities": capabilities, "state": state, "unsupported": errorsByFeature,
	}
}

func transportName(client *cameraClient) string {
	if client.tpap {
		return "tpap"
	}
	if client.secure {
		return "aes-cbc"
	}
	return "legacy"
}

func boolValue(value any) (bool, error) {
	parsed, ok := value.(bool)
	if !ok {
		return false, errors.New("control requires a boolean value")
	}
	return parsed, nil
}

func intValue(value any, minimum, maximum int) (int, error) {
	number, ok := value.(float64)
	if !ok || number != float64(int(number)) {
		return 0, errors.New("control requires an integer value")
	}
	parsed := int(number)
	if parsed < minimum || parsed > maximum {
		return 0, fmt.Errorf("control value must be between %d and %d", minimum, maximum)
	}
	return parsed, nil
}

func setCameraControl(client *cameraClient, name string, value any) (map[string]any, error) {
	switch strings.ToLower(strings.TrimSpace(name)) {
	case "spotlight":
		enabled, err := boolValue(value)
		if err != nil {
			return nil, err
		}
		return client.execute("setLdc", map[string]any{"image": map[string]any{"switch": map[string]any{"force_wtl_state": onOff(enabled)}}})
	case "spotlight_intensity":
		level, err := intValue(value, 1, 100)
		if err != nil {
			return nil, err
		}
		return client.execute("setWhitelampConfig", map[string]any{"image": map[string]any{"switch": map[string]any{"wtl_intensity_level": fmt.Sprint(level)}}})
	case "privacy":
		enabled, err := boolValue(value)
		if err != nil {
			return nil, err
		}
		return client.execute("setLensMaskConfig", map[string]any{"lens_mask": map[string]any{"lens_mask_info": map[string]any{"enabled": onOff(enabled)}}})
	case "led":
		enabled, err := boolValue(value)
		if err != nil {
			return nil, err
		}
		return client.execute("setLedStatus", map[string]any{"led": map[string]any{"config": map[string]any{"enabled": onOff(enabled)}}})
	case "night_vision":
		mode, ok := value.(string)
		if !ok || (mode != "on" && mode != "off" && mode != "auto") {
			return nil, errors.New("night_vision must be on, off, or auto")
		}
		return client.execute("setDayNightModeConfig", map[string]any{"image": map[string]any{"common": map[string]any{"inf_type": mode}}})
	case "siren":
		enabled, err := boolValue(value)
		if err != nil {
			return nil, err
		}
		action := "stop"
		if enabled {
			action = "start"
		}
		return client.execute(map[bool]string{true: "startManualAlarm", false: "stopManualAlarm"}[enabled], map[string]any{"msg_alarm": map[string]any{"manual_msg_alarm": map[string]any{"action": action}}})
	case "microphone_volume":
		level, err := intValue(value, 0, 100)
		if err != nil {
			return nil, err
		}
		return client.execute("setMicrophoneVolume", map[string]any{"method": "set", "audio_config": map[string]any{"microphone": map[string]any{"volume": level}}})
	case "speaker_volume":
		level, err := intValue(value, 0, 100)
		if err != nil {
			return nil, err
		}
		return client.execute("setSpeakerVolume", map[string]any{"method": "set", "audio_config": map[string]any{"speaker": map[string]any{"volume": level}}})
	case "reboot":
		if value != nil {
			if confirm, ok := value.(bool); !ok || !confirm {
				return nil, errors.New("reboot requires value true")
			}
		}
		return client.execute("rebootDevice", map[string]any{"system": map[string]any{"reboot": "null"}})
	default:
		return nil, errors.New("unsupported Tapo control")
	}
}

func onOff(value bool) string {
	if value {
		return "on"
	}
	return "off"
}
