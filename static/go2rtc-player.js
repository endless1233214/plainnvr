import { VideoRTC } from "./vendor/go2rtc/video-rtc.js";

class PlainNVRLivePlayer extends VideoRTC {
  constructor() {
    super();
    this.mode = "mse,hls,mjpeg";
    this.media = "video,audio";
    this.ready = false;
  }

  oninit() {
    super.oninit();
    this.video.muted = true;
    this.video.controls = true;
    this.video.addEventListener("playing", () => {
      this.ready = true;
      this.dispatchState("playing", this.currentMode || "go2rtc");
    });
  }

  onconnect() {
    const connecting = super.onconnect();
    if (connecting) {
      this.ready = false;
      this.currentMode = "";
      this.dispatchState("connecting", "go2rtc");
    }
    return connecting;
  }

  onopen() {
    const modes = super.onopen();
    this.onmessage.plainnvr = (message) => {
      if (["mse", "hls", "mp4", "mjpeg"].includes(message.type)) {
        this.currentMode = message.type;
        this.dispatchState("mode", message.type);
      } else if (message.type === "error") {
        this.dispatchState("warning", String(message.value || "Stream error"));
      }
    };
    return modes;
  }

  onclose() {
    const reconnecting = super.onclose();
    if (reconnecting) {
      this.ready = false;
      this.dispatchState("reconnecting", "go2rtc");
    }
    return reconnecting;
  }

  start(streamName) {
    this.stop();
    this.hidden = false;
    this.src = `/go2rtc/api/ws?src=${encodeURIComponent(streamName)}`;
  }

  stop() {
    this.ready = false;
    this.currentMode = "";
    if (this.video) {
      this.ondisconnect();
    }
    this.hidden = true;
  }

  dispatchState(state, detail) {
    this.dispatchEvent(
      new CustomEvent("plainnvr-stream-state", {
        detail: { state, detail },
      })
    );
  }
}

customElements.define("plainnvr-live-player", PlainNVRLivePlayer);
