const state = {
  cameras: [],
  recorders: {},
  users: [],
  username: "",
  coverage: {},
  nightModes: {},
  selectedCameraId: "",
  liveCameraId: "",
  streamToken: "",
};

const dayKeys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const liveModeStorageKey = "plainnvr-live-mode";
const liveAudioStorageKey = "plainnvr-live-audio";
const liveVolumeStorageKey = "plainnvr-live-volume";

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
  const tokenSuffix = token ? `&${token}` : "";
  const hlsParams = new URLSearchParams({ fps: "10", width: "1280" });
  if (state.streamToken) {
    hlsParams.set("token", state.streamToken);
  }
  return {
    mjpeg: `${base}/ha/${camera.id}/stream.mjpeg?fps=2&width=1280${tokenSuffix}`,
    hls: `${base}/live/${camera.id}/stream.m3u8?${hlsParams.toString()}`,
    snapshot: `${base}/ha/${camera.id}/snapshot.jpg${token ? `?${token}` : ""}`,
  };
}

function cameraLiveMjpegUrl(camera) {
  const fps = Number($("liveFps").value) || 2;
  const width = Number($("liveWidth").value) || 1280;
  const token = state.streamToken || "";
  const params = new URLSearchParams({
    fps: String(Math.max(1, Math.min(fps, 15))),
    width: String(Math.max(320, Math.min(width, 1920))),
  });
  if (token) {
    params.set("token", token);
  }
  return `/ha/${camera.id}/stream.mjpeg?${params.toString()}`;
}

function cameraLiveHlsUrl(camera) {
  const fps = Number($("liveFps").value) || 10;
  const width = Number($("liveWidth").value) || 1280;
  const params = new URLSearchParams({
    fps: String(Math.max(1, Math.min(fps, 15))),
    width: String(Math.max(320, Math.min(width, 1920))),
  });
  if (state.streamToken) {
    params.set("token", state.streamToken);
  }
  const query = params.toString();
  return `/live/${camera.id}/stream.m3u8${query ? `?${query}` : ""}`;
}

function browserCanPlayHls(video) {
  return Boolean(
    video.canPlayType("application/vnd.apple.mpegurl") ||
      video.canPlayType("application/x-mpegURL")
  );
}

function applyLiveAudioSettings() {
  const video = $("liveVideo");
  const audioEnabled = $("liveAudio").checked;
  const volume = Math.max(0, Math.min(Number($("liveVolume").value) || 0, 100)) / 100;
  video.muted = !audioEnabled;
  video.volume = volume;
  try {
    localStorage.setItem(liveAudioStorageKey, audioEnabled ? "1" : "0");
    localStorage.setItem(liveVolumeStorageKey, String(Math.round(volume * 100)));
  } catch (_error) {
    // The live player still works when local storage is unavailable.
  }
}

function syncLiveControls() {
  const hlsMode = $("liveMode").value === "hls";
  $("liveAudio").disabled = !hlsMode;
  $("liveVolume").disabled = !hlsMode || !$("liveAudio").checked;
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
    grayscale_mode: $("grayscaleMode").value,
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
  $("grayscaleMode").value = "off";
  applyScheduleToForm({ mode: "always", days: {} });
  $("deleteCamera").hidden = true;
  renderHaPanel(null);
  setSaveState("");
  renderCameras();
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
  $("grayscaleMode").value = camera.grayscale_mode || "off";
  applyScheduleToForm(camera.schedule);
  $("deleteCamera").hidden = false;
  renderHaPanel(camera);
  setSaveState("");
  renderCameras();
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
    const night = state.nightModes[camera.id];
    const running = recorder?.running;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `camera-item ${camera.id === state.selectedCameraId ? "active" : ""}`;
    button.innerHTML = `
      <strong>${escapeHtml(camera.name)}</strong>
      <div class="camera-meta">
        <span class="chip ${running ? "ok" : camera.enabled ? "warn" : "off"}">${running ? "recording" : camera.enabled ? "waiting" : "disabled"}</span>
        ${
          camera.grayscale_mode === "auto"
            ? `<span class="chip ${night?.night ? "ok" : "off"}">${night?.night ? "night" : "day"}</span>`
            : camera.grayscale_mode === "always"
              ? '<span class="chip ok">gray</span>'
              : ""
        }
        <span class="chip">${camera.segment_seconds}s</span>
        <span class="chip">${camera.retention_days}d</span>
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
  state.nightModes = data.night_modes || {};
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
  const requestedMode = $("liveMode").value;
  const video = $("liveVideo");
  const image = $("liveImage");
  video.pause();
  video.removeAttribute("src");
  video.load();
  image.removeAttribute("src");
  $("liveEmpty").hidden = true;
  image.hidden = true;
  video.hidden = true;

  if (requestedMode === "hls" && browserCanPlayHls(video)) {
    applyLiveAudioSettings();
    video.src = cameraLiveHlsUrl(camera);
    video.hidden = false;
    video.play().catch((error) => {
      $("liveState").textContent = error.message || "Playback blocked";
    });
    $("liveState").textContent = `${camera.name} HLS`;
  } else {
    if (requestedMode === "hls") {
      $("liveMode").value = "mjpeg";
    }
    image.src = cameraLiveMjpegUrl(camera);
    image.hidden = false;
    $("liveState").textContent = `${camera.name} MJPEG`;
  }
  syncLiveControls();
  $("stopLive").disabled = false;
}

function stopLive() {
  const video = $("liveVideo");
  video.pause();
  video.removeAttribute("src");
  video.load();
  $("liveImage").removeAttribute("src");
  $("liveImage").hidden = true;
  video.hidden = true;
  $("liveEmpty").hidden = false;
  $("liveState").textContent = "";
  $("stopLive").disabled = state.cameras.length === 0;
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
  $("newCamera").addEventListener("click", resetForm);
  $("deleteCamera").addEventListener("click", deleteSelectedCamera);
  $("testStream").addEventListener("click", testStream);
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
  });
  $("liveFps").addEventListener("change", () => {
    if ($("liveImage").src || $("liveVideo").src) startLive();
  });
  $("liveWidth").addEventListener("change", () => {
    if ($("liveImage").src || $("liveVideo").src) startLive();
  });
  $("liveMode").addEventListener("change", () => {
    try {
      localStorage.setItem(liveModeStorageKey, $("liveMode").value);
    } catch (_error) {
      // Mode persistence is optional.
    }
    syncLiveControls();
    if ($("liveImage").src || $("liveVideo").src) startLive();
  });
  $("liveAudio").addEventListener("change", () => {
    applyLiveAudioSettings();
    syncLiveControls();
  });
  $("liveVolume").addEventListener("input", () => {
    applyLiveAudioSettings();
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
  try {
    const savedMode = localStorage.getItem(liveModeStorageKey);
    if (savedMode === "hls" || savedMode === "mjpeg") $("liveMode").value = savedMode;
    const savedAudio = localStorage.getItem(liveAudioStorageKey);
    if (savedAudio === "0" || savedAudio === "1") $("liveAudio").checked = savedAudio === "1";
    const savedVolume = Number(localStorage.getItem(liveVolumeStorageKey));
    if (Number.isFinite(savedVolume)) {
      $("liveVolume").value = String(Math.max(0, Math.min(savedVolume, 100)));
    }
  } catch (_error) {
    // Defaults are fine.
  }
  applyLiveAudioSettings();
  syncLiveControls();
  loadStatus().then(loadCoverage).catch((error) => {
    $("diskLine").textContent = error.message;
  });
  setInterval(loadStatus, 10000);
});
