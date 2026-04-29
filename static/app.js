const state = {
  cameras: [],
  recorders: {},
  selectedCameraId: "",
};

const dayKeys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

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
  return new Date().toISOString().slice(0, 10);
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

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
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
  return {
    mjpeg: `${base}/ha/${camera.id}/stream.mjpeg?fps=2&width=1280`,
    snapshot: `${base}/ha/${camera.id}/snapshot.jpg`,
  };
}

function renderHaPanel(camera) {
  const panel = $("haPanel");
  if (!camera?.id) {
    panel.hidden = true;
    $("haMjpegUrl").value = "";
    $("haSnapshotUrl").value = "";
    $("haYaml").value = "";
    return;
  }
  const urls = cameraHaUrls(camera);
  panel.hidden = false;
  $("haMjpegUrl").value = urls.mjpeg;
  $("haSnapshotUrl").value = urls.snapshot;
  $("haYaml").value = [
    "camera:",
    "  - platform: mjpeg",
    `    name: ${camera.name}`,
    `    mjpeg_url: ${urls.mjpeg}`,
    `    still_image_url: ${urls.snapshot}`,
  ].join("\n");
}

function cameraPayloadFromForm() {
  return {
    name: $("cameraName").value.trim(),
    rtsp_url: $("rtspUrl").value.trim(),
    enabled: $("enabled").checked,
    segment_seconds: Number($("segmentSeconds").value),
    retention_days: Number($("retentionDays").value),
    record_audio: $("recordAudio").checked,
    rtsp_transport: $("rtspTransport").value,
    schedule: selectedScheduleFromForm(),
  };
}

function resetForm() {
  state.selectedCameraId = "";
  $("editorTitle").textContent = "Add Camera";
  $("cameraId").value = "";
  $("cameraName").value = "";
  $("rtspUrl").value = "";
  $("enabled").checked = true;
  $("recordAudio").checked = true;
  $("segmentSeconds").value = "60";
  $("retentionDays").value = "14";
  $("rtspTransport").value = "tcp";
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
  $("enabled").checked = camera.enabled;
  $("recordAudio").checked = camera.record_audio;
  $("segmentSeconds").value = String(camera.segment_seconds);
  $("retentionDays").value = String(camera.retention_days);
  $("rtspTransport").value = camera.rtsp_transport || "tcp";
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
    const running = recorder?.running;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `camera-item ${camera.id === state.selectedCameraId ? "active" : ""}`;
    button.innerHTML = `
      <strong>${escapeHtml(camera.name)}</strong>
      <div class="camera-meta">
        <span class="chip ${running ? "ok" : camera.enabled ? "warn" : "off"}">${running ? "recording" : camera.enabled ? "waiting" : "disabled"}</span>
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
  }
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
  updateDiskLine(data.disk);
  renderCameras();
  renderPlaybackCameras();
  renderEvents(data.events);
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
  $("loadSegments").addEventListener("click", loadSegments);
  document.querySelectorAll('input[name="scheduleMode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      $("weeklySchedule").classList.toggle("disabled", radio.value !== "weekly" || !radio.checked);
    });
  });
  loadStatus().catch((error) => {
    $("diskLine").textContent = error.message;
  });
  setInterval(loadStatus, 10000);
});
