const state = {
  cameras: [],
  recorders: {},
  relays: {},
  users: [],
  username: "",
  coverage: {},
  selectedCameraId: "",
  liveCameraId: "",
  streamToken: "",
  ptzBusy: false,
  digitalZoom: 1,
  liveActive: false,
  liveRetryTimer: null,
  liveWatchTimer: null,
  liveLastMediaTime: null,
  liveLastProgressAt: 0,
};

const dayKeys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const victureDirectActions = new Set([
  "up",
  "down",
  "left",
  "right",
  "up_left",
  "up_right",
  "down_left",
  "down_right",
]);
const zoomActions = new Set(["zoom_in", "zoom_out", "stop"]);

const $ = (id) => document.getElementById(id);
const themeStorageKey = "plainnvr-theme";

function preferredTheme() {
  try {
    const saved = localStorage.getItem(themeStorageKey);
    if (saved === "dark" || saved === "light") return saved;
  } catch (_error) {
    return "light";
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme) {
  const nextTheme = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = nextTheme;
  $("themeToggle").checked = nextTheme === "dark";
  $("themeLabel").textContent = nextTheme === "dark" ? "Dark" : "Light";
}

function saveTheme(theme) {
  try {
    localStorage.setItem(themeStorageKey, theme);
  } catch (_error) {
    // Theme persistence is nice to have, not required for the app to work.
  }
  applyTheme(theme);
}

function today() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function localDateTimeValue(value = new Date()) {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 19);
}

function formatBytes(value) {
  if (!Number.isFinite(value)) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let index = 0;
  let size = value;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDate(value) {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString([], {
    month: "short",
    day: "2-digit",
    year: "numeric",
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      window.location.href = "/login.html";
    }
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data;
}

function setSaveState(message) {
  $("saveState").textContent = message || "";
}

function selectedScheduleFromForm() {
  const mode = document.querySelector('input[name="scheduleMode"]:checked').value;
  const days = Object.fromEntries(dayKeys.map((day) => [day, []]));
  if (mode === "weekly") {
    const start = $("scheduleStart").value || "00:00";
    const end = $("scheduleEnd").value || "23:59";
    document.querySelectorAll("#weeklySchedule .day-row input:checked").forEach((checkbox) => {
      days[checkbox.value] = [{ start, end }];
    });
  }
  return { mode, days };
}

function applyScheduleToForm(schedule) {
  const mode = schedule?.mode === "weekly" ? "weekly" : "always";
  document.querySelector(`input[name="scheduleMode"][value="${mode}"]`).checked = true;
  $("weeklySchedule").classList.toggle("disabled", mode !== "weekly");

  const firstWindow = dayKeys.map((day) => schedule?.days?.[day]?.[0]).find(Boolean);
  $("scheduleStart").value = firstWindow?.start || "00:00";
  $("scheduleEnd").value = firstWindow?.end || "23:59";

  document.querySelectorAll("#weeklySchedule .day-row input").forEach((checkbox) => {
    checkbox.checked = Boolean(schedule?.days?.[checkbox.value]?.length);
  });
}

function cameraHaUrls(camera) {
  const base = window.location.origin;
  const token = state.streamToken ? `token=${encodeURIComponent(state.streamToken)}` : "";
  const hlsParams = new URLSearchParams();
  if (state.streamToken) {
    hlsParams.set("token", state.streamToken);
  }
  const hlsQuery = hlsParams.toString();
  return {
    mjpeg: `${base}/ha/${camera.id}/stream.mjpeg${token ? `?${token}` : ""}`,
    hls: `${base}/live/${camera.id}/stream.m3u8${hlsQuery ? `?${hlsQuery}` : ""}`,
    snapshot: `${base}/ha/${camera.id}/snapshot.jpg${token ? `?${token}` : ""}`,
  };
}

function cameraLiveMjpegUrl(camera) {
  const token = state.streamToken || "";
  const params = new URLSearchParams();
  if (token) {
    params.set("token", token);
  }
  const query = params.toString();
  return `/ha/${camera.id}/stream.mjpeg${query ? `?${query}` : ""}`;
}

function cameraLiveHlsUrl(camera) {
  const token = state.streamToken || "";
  const params = new URLSearchParams();
  if (token) {
    params.set("token", token);
  }
  const query = params.toString();
  return `/live/${camera.id}/stream.m3u8${query ? `?${query}` : ""}`;
}

function cameraLiveMode(camera) {
  return camera?.live_view_mode === "mjpeg" ? "mjpeg" : "hls";
}

function liveModeLabel(mode) {
  return mode === "mjpeg" ? "MJPEG" : "HLS / H.264";
}

function cameraZoomMode(camera) {
  const value = camera?.ptz_zoom_mode || "auto";
  if (value === "digital" || value === "hardware" || value === "none") {
    return value;
  }
  return camera?.ptz_type === "victure_direct" ? "digital" : "hardware";
}

function usesDigitalZoom(camera) {
  return cameraZoomMode(camera) === "digital";
}

function usesHardwareZoom(camera) {
  return cameraZoomMode(camera) === "hardware" && camera?.ptz_type !== "victure_direct";
}

function browserCanPlayHls() {
  const video = $("liveVideo");
  return Boolean(
    video.canPlayType("application/vnd.apple.mpegurl") ||
      video.canPlayType("application/x-mpegURL")
  );
}

function renderHaPanel(camera) {
  const panel = $("haPanel");
  const copyButtons = ["copyHaMjpegUrl", "copyHaHlsUrl", "copyHaSnapshotUrl", "copyHaYaml"];
  if (!camera?.id) {
    panel.hidden = true;
    $("haMjpegUrl").value = "";
    $("haHlsUrl").value = "";
    $("haSnapshotUrl").value = "";
    $("haYaml").value = "";
    copyButtons.forEach((id) => {
      $(id).disabled = true;
    });
    return;
  }
  const urls = cameraHaUrls(camera);
  panel.hidden = false;
  $("haMjpegUrl").value = urls.mjpeg;
  $("haHlsUrl").value = urls.hls;
  $("haSnapshotUrl").value = urls.snapshot;
  $("haYaml").value = [
    "camera:",
    "  - platform: mjpeg",
    `    name: ${camera.name}`,
    `    mjpeg_url: ${urls.mjpeg}`,
    `    still_image_url: ${urls.snapshot}`,
  ].join("\n");
  copyButtons.forEach((id) => {
    $(id).disabled = false;
  });
}

function cameraPayloadFromForm() {
  return {
    name: $("cameraName").value.trim(),
    rtsp_url: $("rtspUrl").value.trim(),
    audio_url: $("audioUrl").value.trim(),
    enabled: $("enabled").checked,
    segment_seconds: Number($("segmentSeconds").value),
    retention_days: Number($("retentionDays").value),
    record_audio: $("recordAudio").checked,
    rtsp_transport: $("rtspTransport").value,
    live_view_mode: $("liveViewMode").value,
    ptz_enabled: $("ptzEnabled").checked,
    ptz_type: $("ptzType").value,
    ptz_url: $("ptzUrl").value.trim(),
    ptz_profile_token: $("ptzProfileToken").value.trim(),
    ptz_zoom_mode: $("ptzZoomMode").value,
    ptz_speed: Number($("ptzSpeed").value),
    schedule: selectedScheduleFromForm(),
  };
}

function resetForm() {
  state.selectedCameraId = "";
  $("editorTitle").textContent = "Add Camera";
  $("cameraId").value = "";
  $("cameraName").value = "";
  $("rtspUrl").value = "";
  $("audioUrl").value = "";
  $("enabled").checked = true;
  $("recordAudio").checked = true;
  $("segmentSeconds").value = "60";
  $("retentionDays").value = "14";
  $("rtspTransport").value = "tcp";
  $("liveViewMode").value = "hls";
  $("ptzEnabled").checked = false;
  $("ptzType").value = "onvif";
  $("ptzUrl").value = "";
  $("ptzProfileToken").value = "Profile_1";
  $("ptzZoomMode").value = "auto";
  $("ptzSpeed").value = "0.55";
  $("cameraTime").value = localDateTimeValue();
  $("cameraTimePanel").hidden = true;
  $("cameraTimeState").textContent = "";
  applyScheduleToForm({ mode: "always", days: {} });
  $("deleteCamera").hidden = true;
  renderHaPanel(null);
  setSaveState("");
  renderCameras();
  updatePtzFormHints();
}

function editCamera(camera) {
  state.selectedCameraId = camera.id;
  $("editorTitle").textContent = camera.name;
  $("cameraId").value = camera.id;
  $("cameraName").value = camera.name;
  $("rtspUrl").value = camera.rtsp_url;
  $("audioUrl").value = camera.audio_url || "";
  $("enabled").checked = camera.enabled;
  $("recordAudio").checked = camera.record_audio;
  $("segmentSeconds").value = String(camera.segment_seconds);
  $("retentionDays").value = String(camera.retention_days);
  $("rtspTransport").value = camera.rtsp_transport || "tcp";
  $("liveViewMode").value = cameraLiveMode(camera);
  $("ptzEnabled").checked = Boolean(camera.ptz_enabled);
  $("ptzType").value = camera.ptz_type || "onvif";
  $("ptzUrl").value = camera.ptz_url || "";
  $("ptzProfileToken").value = camera.ptz_profile_token || "Profile_1";
  $("ptzZoomMode").value = camera.ptz_zoom_mode || "auto";
  $("ptzSpeed").value = String(camera.ptz_speed || 0.55);
  $("cameraTime").value = localDateTimeValue();
  $("cameraTimePanel").hidden = !camera.time_sync_supported;
  $("cameraTimeState").textContent = "";
  applyScheduleToForm(camera.schedule);
  $("deleteCamera").hidden = false;
  renderHaPanel(camera);
  setSaveState("");
  renderCameras();
  updatePtzFormHints();
}

function updatePtzFormHints() {
  const driver = $("ptzType").value;
  if (driver === "victure_direct") {
    $("ptzUrl").placeholder = "http://192.168.1.135:8088";
    if ($("ptzProfileToken").value === "nTBCS19C") {
      $("ptzProfileToken").value = "Profile_1";
    }
  } else if (driver === "victure_dvrip") {
    $("ptzUrl").placeholder = "dvrip://192.168.1.135:34567";
    if (!$("ptzProfileToken").value || $("ptzProfileToken").value === "Profile_1") {
      $("ptzProfileToken").value = "nTBCS19C";
    }
  } else {
    $("ptzUrl").placeholder = "http://camera-ip:8080/onvif/ptz_service";
    if (driver === "onvif" && $("ptzProfileToken").value === "nTBCS19C") {
      $("ptzProfileToken").value = "Profile_1";
    }
  }
}

function renderCameras() {
  const list = $("cameraList");
  if (!state.cameras.length) {
    list.innerHTML = '<div class="empty">No cameras yet.</div>';
    return;
  }

  list.innerHTML = "";
  state.cameras.forEach((camera) => {
    const recorder = state.recorders[camera.id];
    const relay = state.relays[camera.id];
    const running = recorder?.running;
    const streamHealthy = relay?.healthy === true;
    const stateLabel = !camera.enabled
      ? "disabled"
      : streamHealthy && running
        ? "recording"
        : streamHealthy
          ? "live"
          : "recovering";
    const stateClass = !camera.enabled ? "off" : streamHealthy ? "ok" : "warn";
    const button = document.createElement("button");
    button.type = "button";
    button.className = `camera-item ${camera.id === state.selectedCameraId ? "active" : ""}`;
    button.innerHTML = `
      <strong>${escapeHtml(camera.name)}</strong>
      <div class="camera-meta">
        <span class="chip ${stateClass}">${stateLabel}</span>
        <span class="chip">${camera.segment_seconds}s</span>
        <span class="chip">${camera.retention_days}d</span>
        <span class="chip">${liveModeLabel(cameraLiveMode(camera))}</span>
        ${camera.ptz_enabled ? '<span class="chip ok">ptz</span>' : ""}
      </div>
    `;
    button.addEventListener("click", () => editCamera(camera));
    list.appendChild(button);
  });
}

function renderPlaybackCameras() {
  const select = $("playbackCamera");
  const current = select.value;
  select.innerHTML = "";
  state.cameras.forEach((camera) => {
    const option = document.createElement("option");
    option.value = camera.id;
    option.textContent = camera.name;
    select.appendChild(option);
  });
  if (state.cameras.some((camera) => camera.id === current)) {
    select.value = current;
  } else if (state.cameras.length) {
    select.value = state.cameras[0].id;
  }
}

function renderCoverage() {
  const cameraId = $("playbackCamera").value;
  const summary = state.coverage[cameraId];
  const target = $("coverageSummary");
  if (!cameraId) {
    target.className = "coverage-summary empty";
    target.textContent = "No camera selected.";
    return;
  }
  if (!summary) {
    target.className = "coverage-summary empty";
    target.textContent = "No recording summary loaded.";
    return;
  }
  if (!summary.count) {
    target.className = "coverage-summary empty";
    target.textContent = `No saved recordings yet. Retention is ${summary.retention_days} days.`;
    return;
  }

  target.className = "coverage-summary";
  const dates = summary.dates || [];
  const currentDate = $("playbackDate").value;
  const dateButtons = dates
    .slice(-14)
    .reverse()
    .map((date) => {
      const active = date === currentDate ? " active" : "";
      return `<button class="date-chip${active}" type="button" data-date="${date}">${formatDate(date)}</button>`;
    })
    .join("");
  target.innerHTML = `
    <div>
      Saved ${formatTime(summary.oldest)} to ${formatTime(summary.newest)}
      <span>${summary.count} segments</span>
      <span>${formatBytes(summary.total_size)}</span>
      <span>${summary.retention_days}d retention</span>
    </div>
    <div class="date-chips">${dateButtons}</div>
  `;
  target.querySelectorAll("[data-date]").forEach((button) => {
    button.addEventListener("click", () => {
      $("playbackDate").value = button.dataset.date;
      renderCoverage();
      loadSegments().catch((error) => {
        $("segments").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
      });
    });
  });
}

async function loadCoverage() {
  const cameraId = $("playbackCamera").value;
  if (!cameraId) {
    renderCoverage();
    return;
  }
  const data = await api(`/api/coverage?camera_id=${encodeURIComponent(cameraId)}`);
  state.coverage[cameraId] = data.coverage;
  renderCoverage();
}

function renderLiveCameras() {
  const select = $("liveCamera");
  const current = state.liveCameraId || select.value;
  select.innerHTML = "";
  state.cameras.forEach((camera) => {
    const option = document.createElement("option");
    option.value = camera.id;
    option.textContent = camera.name;
    select.appendChild(option);
  });
  if (state.cameras.some((camera) => camera.id === current)) {
    select.value = current;
    state.liveCameraId = current;
  } else if (state.cameras.length) {
    select.value = state.cameras[0].id;
    state.liveCameraId = state.cameras[0].id;
  } else {
    state.liveCameraId = "";
    stopLive();
  }
  const hasCameras = state.cameras.length > 0;
  $("startLive").disabled = !hasCameras;
  $("stopLive").disabled = !hasCameras;
  const selected = selectedLiveCamera();
  $("liveSourceLabel").textContent = selected ? liveModeLabel(cameraLiveMode(selected)) : "";
  renderPtzPanel();
}

function selectedLiveCamera() {
  const cameraId = $("liveCamera").value || state.liveCameraId;
  return state.cameras.find((item) => item.id === cameraId) || null;
}

function renderPtzPanel() {
  const camera = selectedLiveCamera();
  const panel = $("ptzPanel");
  const ptzEnabled = Boolean(camera?.ptz_enabled);
  const directStepper = camera?.ptz_type === "victure_direct";
  const digitalZoom = usesDigitalZoom(camera);
  const hardwareZoom = usesHardwareZoom(camera);
  panel.hidden = !ptzEnabled;
  if (!ptzEnabled) {
    $("ptzState").textContent = "";
  } else if (state.ptzBusy) {
    $("ptzState").textContent = "Moving...";
  }
  panel.querySelectorAll("[data-ptz]").forEach((button) => {
    const action = button.dataset.ptz;
    const isZoom = zoomActions.has(action) || action.startsWith("zoom_");
    const visible = isZoom
      ? digitalZoom || hardwareZoom
      : !directStepper || victureDirectActions.has(action);
    button.hidden = !visible;
    button.disabled = !ptzEnabled || state.ptzBusy || !visible;
  });
}

function renderEvents(events) {
  const target = $("events");
  if (!events.length) {
    target.innerHTML = '<div class="empty">No recorder events yet.</div>';
    return;
  }
  target.innerHTML = "";
  events.forEach((event) => {
    const row = document.createElement("div");
    row.className = "event";
    row.innerHTML = `
      <time>${formatTime(event.created_at)}</time>
      <span class="chip ${event.level === "error" ? "off" : event.level === "warn" ? "warn" : "ok"}">${event.level}</span>
      <span>${escapeHtml(event.message)}</span>
    `;
    target.appendChild(row);
  });
}

function renderUsers() {
  const target = $("userList");
  if (!state.users.length) {
    target.innerHTML = '<div class="empty">No users yet.</div>';
    return;
  }
  target.innerHTML = "";
  state.users.forEach((user) => {
    const row = document.createElement("div");
    row.className = "user-row";
    const isCurrent = user.username === state.username;
    row.innerHTML = `
      <div>
        <strong>${escapeHtml(user.username)}</strong>
        <span>${isCurrent ? "current user" : `created ${formatTime(user.created_at)}`}</span>
      </div>
      <button class="danger" type="button" ${isCurrent ? "disabled" : ""}>Delete</button>
    `;
    row.querySelector("button").addEventListener("click", async () => {
      if (!window.confirm(`Delete user ${user.username}?`)) return;
      await api(`/api/users/${encodeURIComponent(user.username)}`, { method: "DELETE" });
      $("usersState").textContent = "Deleted";
      await loadStatus();
    });
    target.appendChild(row);
  });
}

function updateDiskLine(disk) {
  const used = formatBytes(disk.used);
  const total = formatBytes(disk.total);
  const free = formatBytes(disk.free);
  $("diskLine").textContent = `${used} used of ${total}; ${free} free`;
}

async function loadStatus() {
  const data = await api("/api/status");
  state.cameras = data.cameras;
  state.recorders = data.recorders;
  state.relays = data.relays || {};
  state.users = data.users || [];
  state.username = data.username || "";
  state.streamToken = data.stream_token || "";
  updateDiskLine(data.disk);
  renderCameras();
  renderLiveCameras();
  renderPlaybackCameras();
  renderCoverage();
  renderEvents(data.events);
  renderUsers();
  syncLiveHealth();
}

async function saveCamera(event) {
  event.preventDefault();
  const payload = cameraPayloadFromForm();
  setSaveState("Saving...");
  try {
    const id = $("cameraId").value;
    const camera = id
      ? await api(`/api/cameras/${id}`, { method: "PUT", body: JSON.stringify(payload) })
      : await api("/api/cameras", { method: "POST", body: JSON.stringify(payload) });
    await loadStatus();
    editCamera(camera);
    setSaveState("Saved");
  } catch (error) {
    setSaveState(error.message);
  }
}

async function deleteSelectedCamera() {
  const id = $("cameraId").value;
  if (!id) return;
  const camera = state.cameras.find((item) => item.id === id);
  if (!window.confirm(`Delete ${camera?.name || "this camera"}? Recordings stay on disk.`)) return;
  await api(`/api/cameras/${id}`, { method: "DELETE" });
  resetForm();
  await loadStatus();
}

async function testStream() {
  const payload = cameraPayloadFromForm();
  setSaveState("Testing...");
  try {
    const result = await api("/api/test-stream", { method: "POST", body: JSON.stringify(payload) });
    setSaveState(result.ok ? `OK in ${result.seconds}s` : result.message);
  } catch (error) {
    setSaveState(error.message);
  }
}

function applyCameraTimeResult(result) {
  const parsed = new Date(String(result.time || "").replace(" ", "T"));
  if (!Number.isNaN(parsed.getTime())) {
    $("cameraTime").value = localDateTimeValue(parsed);
  }
  $("cameraTimeState").textContent = result.time ? `Camera: ${result.time}` : "Done";
}

async function readCameraTime() {
  const cameraId = $("cameraId").value;
  if (!cameraId) return;
  $("cameraTimeState").textContent = "Reading...";
  try {
    applyCameraTimeResult(await api(`/api/cameras/${cameraId}/time`));
  } catch (error) {
    $("cameraTimeState").textContent = error.message;
  }
}

async function setCameraTime() {
  const cameraId = $("cameraId").value;
  if (!cameraId) return;
  const value = $("cameraTime").value;
  if (!value) {
    $("cameraTimeState").textContent = "Choose a date and time.";
    return;
  }
  $("cameraTimeState").textContent = "Setting...";
  try {
    applyCameraTimeResult(
      await api(`/api/cameras/${cameraId}/time`, {
        method: "POST",
        body: JSON.stringify({ time: value }),
      })
    );
  } catch (error) {
    $("cameraTimeState").textContent = error.message;
  }
}

async function loadSegments() {
  const cameraId = $("playbackCamera").value;
  if (!cameraId) {
    $("segments").innerHTML = '<div class="empty">No camera selected.</div>';
    return;
  }
  const date = $("playbackDate").value || today();
  $("playbackDate").value = date;
  const data = await api(`/api/segments?camera_id=${encodeURIComponent(cameraId)}&date=${encodeURIComponent(date)}`);
  const target = $("segments");
  $("segmentCount").textContent = `${data.segments.length} segments`;
  if (!data.segments.length) {
    target.innerHTML = '<div class="empty">No recordings for this date.</div>';
    return;
  }
  target.innerHTML = "";
  data.segments.forEach((segment) => {
    const row = document.createElement("div");
    row.className = "segment";
    row.innerHTML = `
      <time>${formatTime(segment.start)}</time>
      <span>${formatBytes(segment.size)}</span>
      <button type="button">Play</button>
    `;
    row.querySelector("button").addEventListener("click", () => {
      $("player").src = segment.url;
      $("player").play().catch(() => {});
    });
    target.appendChild(row);
  });
}

async function saveUser(event) {
  event.preventDefault();
  $("usersState").textContent = "Adding...";
  try {
    await api("/api/users", {
      method: "POST",
      body: JSON.stringify({
        username: $("newUsername").value.trim(),
        password: $("newPassword").value,
      }),
    });
    $("newUsername").value = "";
    $("newPassword").value = "";
    $("usersState").textContent = "Added";
    await loadStatus();
  } catch (error) {
    $("usersState").textContent = error.message;
  }
}

function startLive() {
  const cameraId = $("liveCamera").value;
  const camera = state.cameras.find((item) => item.id === cameraId);
  if (!camera) {
    stopLive();
    $("liveState").textContent = "No camera";
    return;
  }
  state.liveCameraId = camera.id;
  state.liveActive = true;
  state.digitalZoom = 1;
  stopLiveMedia();
  const image = $("liveImage");
  const video = $("liveVideo");
  $("liveEmpty").hidden = true;
  image.hidden = true;
  video.hidden = true;

  const mode = cameraLiveMode(camera);
  $("liveSourceLabel").textContent = liveModeLabel(mode);
  if (mode === "hls") {
    if (!browserCanPlayHls()) {
      startLiveMjpeg(camera, "MJPEG fallback");
      $("liveState").textContent = `${camera.name} MJPEG fallback`;
      $("stopLive").disabled = false;
      renderPtzPanel();
      return;
    }
    video.onplaying = () => {
      $("liveState").textContent = `${camera.name} HLS / H.264`;
      state.liveLastMediaTime = video.currentTime;
      state.liveLastProgressAt = Date.now();
    };
    video.onerror = () => {
      startLiveMjpeg(camera, "MJPEG fallback");
      $("liveState").textContent = `${camera.name} HLS failed; MJPEG fallback`;
      scheduleLiveRetry(camera);
    };
    video.src = cameraLiveHlsUrl(camera);
    video.hidden = false;
    video.play().catch(() => {
      startLiveMjpeg(camera, "MJPEG fallback");
      scheduleLiveRetry(camera);
    });
    $("liveState").textContent = `${camera.name} HLS starting`;
    startLiveWatchdog(camera);
  } else {
    startLiveMjpeg(camera, "MJPEG");
  }
  $("stopLive").disabled = false;
  renderPtzPanel();
}

function startLiveMjpeg(camera, label) {
  clearLiveWatchdog();
  const video = $("liveVideo");
  video.pause();
  video.onplaying = null;
  video.onerror = null;
  video.removeAttribute("src");
  video.load();
  video.hidden = true;
  const image = $("liveImage");
  image.onerror = () => {
    if (!state.liveActive || state.liveCameraId !== camera.id) return;
    image.removeAttribute("src");
    image.hidden = true;
    $("liveEmpty").hidden = false;
    $("liveEmpty").textContent = "Stream unavailable. Retrying...";
    $("liveState").textContent = `${camera.name} stream offline`;
    scheduleLiveRetry(camera, 3000);
  };
  const separator = cameraLiveMjpegUrl(camera).includes("?") ? "&" : "?";
  image.src = `${cameraLiveMjpegUrl(camera)}${separator}reload=${Date.now()}`;
  image.hidden = false;
  $("liveEmpty").hidden = true;
  $("liveSourceLabel").textContent = "MJPEG";
  $("liveState").textContent = `${camera.name} ${label}`;
  applyDigitalZoom();
}

function clearLiveWatchdog() {
  if (state.liveWatchTimer) {
    clearInterval(state.liveWatchTimer);
    state.liveWatchTimer = null;
  }
  state.liveLastMediaTime = null;
  state.liveLastProgressAt = 0;
}

function clearLiveRetry() {
  if (state.liveRetryTimer) {
    clearTimeout(state.liveRetryTimer);
    state.liveRetryTimer = null;
  }
}

function scheduleLiveRetry(camera, delay = 10000) {
  clearLiveRetry();
  state.liveRetryTimer = setTimeout(() => {
    state.liveRetryTimer = null;
    if (state.liveActive && state.liveCameraId === camera.id) {
      const relay = state.relays[camera.id];
      if (relay && !relay.healthy) {
        scheduleLiveRetry(camera, 3000);
        return;
      }
      startLive();
    }
  }, delay);
}

function startLiveWatchdog(camera) {
  clearLiveWatchdog();
  state.liveLastProgressAt = Date.now();
  state.liveWatchTimer = setInterval(() => {
    if (!state.liveActive || state.liveCameraId !== camera.id) return;
    const video = $("liveVideo");
    const current = video.currentTime;
    if (Number.isFinite(current) && (state.liveLastMediaTime === null || current > state.liveLastMediaTime + 0.05)) {
      state.liveLastMediaTime = current;
      state.liveLastProgressAt = Date.now();
      return;
    }
    if (Date.now() - state.liveLastProgressAt > 15000) {
      startLiveMjpeg(camera, "HLS stalled; MJPEG fallback");
      scheduleLiveRetry(camera);
    }
  }, 3000);
}

function syncLiveHealth() {
  if (!state.liveActive) return;
  const camera = selectedLiveCamera();
  if (!camera) return;
  const relay = state.relays[camera.id];
  if (relay && !relay.healthy) {
    stopLiveMedia();
    $("liveEmpty").hidden = false;
    $("liveEmpty").textContent = "Stream offline. Relay is recovering...";
    $("liveState").textContent = `${camera.name} recovering`;
    scheduleLiveRetry(camera, 3000);
    return;
  }
  const hasMedia = Boolean($("liveVideo").getAttribute("src") || $("liveImage").getAttribute("src"));
  if (relay?.healthy && !hasMedia) {
    startLive();
  }
}

function stopLiveMedia() {
  clearLiveWatchdog();
  clearLiveRetry();
  const video = $("liveVideo");
  video.pause();
  video.removeAttribute("src");
  video.load();
  video.onplaying = null;
  video.onerror = null;
  video.hidden = true;
  const image = $("liveImage");
  image.onerror = null;
  image.removeAttribute("src");
  image.hidden = true;
  state.digitalZoom = 1;
  applyDigitalZoom();
}

function stopLive() {
  state.liveActive = false;
  stopLiveMedia();
  $("liveEmpty").hidden = false;
  $("liveEmpty").textContent = "No live stream selected.";
  $("liveState").textContent = "";
  $("stopLive").disabled = state.cameras.length === 0;
  renderPtzPanel();
}

async function sendPtzCommand(action) {
  const camera = selectedLiveCamera();
  if (!camera?.ptz_enabled) return;
  if (zoomActions.has(action) && usesDigitalZoom(camera)) {
    adjustDigitalZoom(action);
    $("ptzState").textContent =
      action === "stop" ? "Digital zoom reset" : `Digital zoom ${Math.round(state.digitalZoom * 100)}%`;
    return;
  }
  if (zoomActions.has(action) && !usesHardwareZoom(camera)) {
    $("ptzState").textContent = "Zoom disabled";
    return;
  }
  state.ptzBusy = true;
  renderPtzPanel();
  $("ptzState").textContent = "Sending...";
  try {
    const result = await api(`/api/cameras/${camera.id}/ptz`, {
      method: "POST",
      body: JSON.stringify({
        action,
        speed: camera.ptz_speed || 0.55,
        duration_ms: action === "stop" || action === "home" ? 0 : 300,
      }),
    });
    $("ptzState").textContent = result.warning || "OK";
  } catch (error) {
    $("ptzState").textContent = error.message;
  } finally {
    state.ptzBusy = false;
    renderPtzPanel();
  }
}

function adjustDigitalZoom(action) {
  if (action === "zoom_in") {
    state.digitalZoom = Math.min(4, Math.round((state.digitalZoom + 0.25) * 100) / 100);
  } else if (action === "zoom_out") {
    state.digitalZoom = Math.max(1, Math.round((state.digitalZoom - 0.25) * 100) / 100);
  } else {
    state.digitalZoom = 1;
  }
  applyDigitalZoom();
}

function applyDigitalZoom() {
  const transform = `scale(${state.digitalZoom})`;
  ["liveVideo", "liveImage"].forEach((id) => {
    const element = $(id);
    element.style.transform = transform;
  });
}

async function logout() {
  await fetch("/api/auth/logout", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
  }).catch(() => {});
  window.location.href = "/login.html";
}

async function copyValue(elementId) {
  const value = $(elementId).value;
  if (!value) return;
  await navigator.clipboard.writeText(value);
  setSaveState("Copied");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

document.addEventListener("DOMContentLoaded", () => {
  applyTheme(preferredTheme());
  $("themeToggle").addEventListener("change", (event) => {
    saveTheme(event.target.checked ? "dark" : "light");
  });
  $("playbackDate").value = today();
  $("cameraForm").addEventListener("submit", saveCamera);
  $("ptzType").addEventListener("change", updatePtzFormHints);
  $("newCamera").addEventListener("click", resetForm);
  $("deleteCamera").addEventListener("click", deleteSelectedCamera);
  $("testStream").addEventListener("click", testStream);
  $("cameraTimeNow").addEventListener("click", () => {
    $("cameraTime").value = localDateTimeValue();
    $("cameraTimeState").textContent = "";
  });
  $("readCameraTime").addEventListener("click", readCameraTime);
  $("setCameraTime").addEventListener("click", setCameraTime);
  $("refreshStatus").addEventListener("click", loadStatus);
  $("logoutButton").addEventListener("click", logout);
  $("loadSegments").addEventListener("click", loadSegments);
  $("userForm").addEventListener("submit", saveUser);
  $("copyHaMjpegUrl").addEventListener("click", () => copyValue("haMjpegUrl"));
  $("copyHaHlsUrl").addEventListener("click", () => copyValue("haHlsUrl"));
  $("copyHaSnapshotUrl").addEventListener("click", () => copyValue("haSnapshotUrl"));
  $("copyHaYaml").addEventListener("click", () => copyValue("haYaml"));
  $("startLive").addEventListener("click", startLive);
  $("stopLive").addEventListener("click", stopLive);
  $("liveCamera").addEventListener("change", (event) => {
    state.liveCameraId = event.target.value;
    const camera = selectedLiveCamera();
    $("liveSourceLabel").textContent = camera ? liveModeLabel(cameraLiveMode(camera)) : "";
    renderPtzPanel();
    if (state.liveActive) {
      startLive();
    }
  });
  document.querySelectorAll("[data-ptz]").forEach((button) => {
    button.addEventListener("click", () => {
      sendPtzCommand(button.dataset.ptz).catch((error) => {
        $("ptzState").textContent = error.message;
      });
    });
  });
  $("playbackCamera").addEventListener("change", () => {
    loadCoverage().catch((error) => {
      $("coverageSummary").textContent = error.message;
    });
  });
  $("playbackDate").addEventListener("change", renderCoverage);
  stopLive();
  document.querySelectorAll('input[name="scheduleMode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      $("weeklySchedule").classList.toggle("disabled", radio.value !== "weekly" || !radio.checked);
    });
  });
  loadStatus().then(loadCoverage).catch((error) => {
    $("diskLine").textContent = error.message;
  });
  setInterval(loadStatus, 10000);
});
