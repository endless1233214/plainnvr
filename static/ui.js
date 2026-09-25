(() => {
  const pageTitles = {
    dashboard: "Dashboard",
    live: "Live View",
    cameras: "Cameras",
    recordings: "Recordings",
    events: "Events",
    settings: "Settings",
  };

  const wallCameraStorageKey = "plainnvr-live-wall-cameras";
  const wallLayoutStorageKey = "plainnvr-live-wall-layout";
  let activePage = "dashboard";

  function el(id) {
    return document.getElementById(id);
  }

  function safeStorageGet(key) {
    try {
      return localStorage.getItem(key);
    } catch (_error) {
      return null;
    }
  }

  function safeStorageSet(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (_error) {
      // The UI still works without persisted preferences.
    }
  }

  function normalizedPage(value) {
    const page = String(value || "").replace(/^#/, "").trim().toLowerCase();
    return pageTitles[page] ? page : "dashboard";
  }

  function navigate(page, { updateHash = true } = {}) {
    const next = normalizedPage(page);
    activePage = next;

    document.querySelectorAll("[data-page]").forEach((section) => {
      const active = section.dataset.page === next;
      section.hidden = !active;
      section.classList.toggle("active", active);
    });

    document.querySelectorAll(".nav-item[data-page-target]").forEach((button) => {
      const active = button.dataset.pageTarget === next;
      button.classList.toggle("active", active);
      button.setAttribute("aria-current", active ? "page" : "false");
    });

    const title = el("pageTitle");
    if (title) title.textContent = pageTitles[next];

    if (updateHash && window.location.hash !== `#${next}`) {
      history.pushState(null, "", `#${next}`);
    }

    if (next === "cameras" && typeof maskRtspUrl === "function") maskRtspUrl();

    if (next === "live") {
      renderLiveWall();
    } else {
      stopWallPlayers();
      if (typeof stopLive === "function" && state.liveActive) {
        stopLive();
      }
    }
  }

  function wallCapacity() {
    const value = el("wallLayout")?.value || "auto";
    return value === "auto" ? 9 : Math.max(1, Number(value) || 4);
  }

  function storedWallIds() {
    const raw = safeStorageGet(wallCameraStorageKey);
    if (!raw) return null;
    try {
      const value = JSON.parse(raw);
      return Array.isArray(value) ? value.map(String) : null;
    } catch (_error) {
      return null;
    }
  }

  function selectedWallIds() {
    const available = new Set((state.cameras || []).map((camera) => camera.id));
    const stored = storedWallIds();
    if (stored !== null) return stored.filter((id) => available.has(id));
    return (state.cameras || [])
      .filter((camera) => camera.enabled)
      .map((camera) => camera.id)
      .slice(0, 9);
  }

  function saveWallIds(ids) {
    safeStorageSet(wallCameraStorageKey, JSON.stringify(ids));
  }

  function cameraState(camera) {
    const recorder = state.recorders?.[camera.id];
    const relay = state.relays?.[camera.id];

    if (!camera.enabled) {
      return { label: "disabled", className: "off", issue: true };
    }
    if (relay?.available !== true || relay?.media_state === "stalled") {
      return { label: "recovering", className: "warn", issue: true };
    }
    if (recorder?.paused) {
      return { label: "paused", className: "warn", issue: false };
    }
    if (recorder?.running) {
      return { label: "recording", className: "ok", issue: false };
    }
    return { label: "live", className: "ok", issue: false };
  }

  function renderDashboard() {
    const cameras = state.cameras || [];
    const recording = cameras.filter((camera) => state.recorders?.[camera.id]?.running).length;
    const attention = cameras.filter((camera) => cameraState(camera).issue).length;

    if (el("dashboardCameraCount")) {
      el("dashboardCameraCount").textContent = String(cameras.length);
      el("dashboardCameraDetail").textContent =
        cameras.length === 1 ? "1 camera configured" : `${cameras.length} cameras configured`;
    }

    if (el("dashboardRecordingCount")) {
      el("dashboardRecordingCount").textContent = String(recording);
      el("dashboardRecordingDetail").textContent =
        recording === 1 ? "1 recorder active" : `${recording} recorders active`;
    }

    if (el("dashboardStorage")) {
      const disk = state.disk || {};
      el("dashboardStorage").textContent =
        Number.isFinite(disk.free) ? formatBytes(disk.free) : "—";
      el("dashboardStorageDetail").textContent =
        Number.isFinite(disk.total)
          ? `${formatBytes(disk.used)} used of ${formatBytes(disk.total)}`
          : "Storage unavailable";
    }

    if (el("dashboardHealth")) {
      el("dashboardHealth").textContent = String(attention);
      el("dashboardHealthDetail").textContent =
        attention === 0
          ? "Everything looks good"
          : attention === 1
            ? "1 camera needs attention"
            : `${attention} cameras need attention`;
    }

    const grid = el("dashboardCameraGrid");
    if (grid) {
      grid.innerHTML = "";
      if (!cameras.length) {
        grid.innerHTML = '<div class="empty">No cameras configured yet.</div>';
      } else {
        cameras.forEach((camera) => {
          const status = cameraState(camera);
          const card = document.createElement("article");
          card.className = "dashboard-camera-card";
          card.innerHTML = `
            <header>
              <strong>${escapeHtml(camera.name)}</strong>
              <span class="chip ${status.className}">${status.label}</span>
            </header>
            <div class="camera-card-meta">
              <span class="chip">${camera.segment_seconds}s segments</span>
              <span class="chip">${camera.retention_days}d retention</span>
              ${camera.ptz_enabled ? '<span class="chip ok">PTZ</span>' : ""}
            </div>
            <div>
              <button type="button" data-dashboard-live>Live</button>
              <button type="button" data-dashboard-settings>Settings</button>
            </div>
          `;
          card.querySelector("[data-dashboard-live]").addEventListener("click", () => {
            navigate("live");
            const select = el("liveCamera");
            if (select) {
              select.value = camera.id;
              state.liveCameraId = camera.id;
              select.dispatchEvent(new Event("change"));
              if (!state.liveActive) startLive();
            }
          });
          card.querySelector("[data-dashboard-settings]").addEventListener("click", () => {
            editCamera(camera);
            navigate("cameras");
          });
          grid.appendChild(card);
        });
      }
    }

    const events = el("dashboardEvents");
    if (events) {
      const recent = (state.events || []).slice(0, 8);
      events.innerHTML = "";
      if (!recent.length) {
        events.innerHTML = '<div class="empty">No recent events.</div>';
      } else {
        recent.forEach((event) => {
          const item = document.createElement("article");
          item.className = "dashboard-event";
          const levelClass =
            event.level === "error" ? "off" : event.level === "warn" ? "warn" : "ok";
          item.innerHTML = `
            <div>
              <span class="chip ${levelClass}">${escapeHtml(event.level)}</span>
              <time>${formatTime(event.created_at)}</time>
            </div>
            <p>${escapeHtml(event.message)}</p>
          `;
          events.appendChild(item);
        });
      }
    }
  }

  function renderWallCameraPicker() {
    const target = el("wallCameraPicker");
    if (!target) return;

    const selected = new Set(selectedWallIds());
    target.innerHTML = "";

    if (!(state.cameras || []).length) {
      target.innerHTML = '<div class="empty">No cameras configured.</div>';
      return;
    }

    state.cameras.forEach((camera) => {
      const option = document.createElement("label");
      option.className = "camera-picker-option";
      option.innerHTML = `
        <input type="checkbox" value="${camera.id}" ${selected.has(camera.id) ? "checked" : ""} />
        <span>${escapeHtml(camera.name)}</span>
      `;
      const checkbox = option.querySelector("input");
      checkbox.addEventListener("change", () => {
        const next = new Set(selectedWallIds());
        if (checkbox.checked) next.add(camera.id);
        else next.delete(camera.id);
        saveWallIds([...next]);
        renderLiveWall();
      });
      target.appendChild(option);
    });
  }

  function wallTile(camera) {
    const tile = document.createElement("article");
    tile.className = "wall-tile";
    tile.dataset.cameraId = camera.id;
    tile.innerHTML = `
      <plainnvr-live-player hidden></plainnvr-live-player>
      <div class="wall-tile-empty">Connecting…</div>
      <div class="wall-tile-header">
        <strong>${escapeHtml(camera.name)}</strong>
        <span class="wall-tile-state">connecting</span>
      </div>
      <div class="wall-tile-actions">
        <button type="button" data-focus>Focus</button>
        <button type="button" data-fullscreen>Fullscreen</button>
      </div>
    `;

    tile.querySelector("[data-focus]").addEventListener("click", () => {
      const select = el("liveCamera");
      if (!select) return;
      select.value = camera.id;
      state.liveCameraId = camera.id;
      select.dispatchEvent(new Event("change"));
      if (!state.liveActive) startLive();
      el("go2rtcLive")?.scrollIntoView({ behavior: "smooth", block: "center" });
    });

    tile.querySelector("[data-fullscreen]").addEventListener("click", () => {
      tile.requestFullscreen?.();
    });

    const player = tile.querySelector("plainnvr-live-player");
    player.addEventListener("plainnvr-stream-state", (event) => {
      const label = tile.querySelector(".wall-tile-state");
      const empty = tile.querySelector(".wall-tile-empty");
      const streamState = event.detail?.state;
      const detail = event.detail?.detail;

      if (streamState === "playing") {
        label.textContent = String(detail || "live").toUpperCase();
        empty.hidden = true;
      } else if (streamState === "mode") {
        label.textContent = String(detail || "live").toUpperCase();
      } else if (streamState === "warning") {
        label.textContent = "warning";
        empty.hidden = false;
        empty.textContent = String(detail || "Stream warning");
      } else if (streamState === "reconnecting") {
        label.textContent = "reconnecting";
        empty.hidden = false;
        empty.textContent = "Reconnecting…";
      } else if (streamState === "connecting") {
        label.textContent = "connecting";
      }
    });

    return tile;
  }

  function syncWallTile(tile, camera) {
    tile.querySelector(".wall-tile-header strong").textContent = camera.name;
    const player = tile.querySelector("plainnvr-live-player");
    const empty = tile.querySelector(".wall-tile-empty");
    const label = tile.querySelector(".wall-tile-state");
    const relay = state.relays?.[camera.id];
    const status = cameraState(camera);

    if (!camera.enabled) {
      player.stop?.();
      player.dataset.stream = "";
      empty.hidden = false;
      empty.textContent = "Camera disabled";
      label.textContent = "disabled";
      return;
    }

    if (state.go2rtc?.running !== true || !relay?.stream || relay?.running === false) {
      player.stop?.();
      player.dataset.stream = "";
      empty.hidden = false;
      empty.textContent = "Stream recovering…";
      label.textContent = "recovering";
      return;
    }

    const stream = relay.stream;
    if (typeof player.start !== "function") {
      empty.hidden = false;
      empty.textContent = "Live player loading…";
      return;
    }

    if (player.dataset.stream !== stream || player.hidden) {
      player.dataset.stream = stream;
      player.start(stream);
    }

    if (typeof applyMediaViewTransform === "function") {
      applyMediaViewTransform(player, camera, 1);
    }
    label.textContent = status.label;
  }

  function stopWallPlayers() {
    const wall = el("liveWall");
    if (!wall) return;
    wall.querySelectorAll("plainnvr-live-player").forEach((player) => {
      player.stop?.();
      player.dataset.stream = "";
    });
  }

  function renderLiveWall() {
    if (activePage !== "live") return;

    const wall = el("liveWall");
    if (!wall) return;

    const layout = el("wallLayout")?.value || "auto";
    wall.dataset.layout = layout;

    const selected = new Set(selectedWallIds());
    const cameras = (state.cameras || [])
      .filter((camera) => selected.has(camera.id))
      .slice(0, wallCapacity());

    const keep = new Set(cameras.map((camera) => camera.id));
    wall.querySelectorAll(".wall-tile").forEach((tile) => {
      if (!keep.has(tile.dataset.cameraId)) {
        tile.querySelector("plainnvr-live-player")?.stop?.();
        tile.remove();
      }
    });
    wall.querySelector(".wall-empty")?.remove();

    if (!cameras.length) {
      stopWallPlayers();
      wall.innerHTML = '<div class="wall-empty">Choose one or more cameras from the Cameras menu above.</div>';
      return;
    }

    cameras.forEach((camera) => {
      let tile = wall.querySelector(`.wall-tile[data-camera-id="${CSS.escape(camera.id)}"]`);
      if (!tile) {
        tile = wallTile(camera);
        wall.appendChild(tile);
      }
      syncWallTile(tile, camera);
    });
  }

  function revealStreamUrl() {
    const input = el("rtspUrl");
    const button = el("toggleRtspVisibility");
    if (!input || !button) return;

    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.textContent = show ? "Hide" : "Show";
    button.setAttribute("aria-pressed", show ? "true" : "false");
  }

  function render() {
    renderDashboard();
    renderWallCameraPicker();
    if (activePage === "live") {
      renderLiveWall();
    }
  }

  function init() {
    document.querySelectorAll("[data-page-target]").forEach((button) => {
      button.addEventListener("click", () => navigate(button.dataset.pageTarget));
    });

    const syncFromLocation = () => {
      if (normalizedPage(window.location.hash) !== activePage) {
        navigate(window.location.hash, { updateHash: false });
      }
    };
    window.addEventListener("hashchange", syncFromLocation);
    window.addEventListener("popstate", syncFromLocation);

    const layout = safeStorageGet(wallLayoutStorageKey);
    if (layout && el("wallLayout")?.querySelector(`option[value="${layout}"]`)) {
      el("wallLayout").value = layout;
    }
    el("wallLayout")?.addEventListener("change", () => {
      safeStorageSet(wallLayoutStorageKey, el("wallLayout").value);
      renderLiveWall();
    });

    el("toggleRtspVisibility")?.addEventListener("click", revealStreamUrl);

    navigate(window.location.hash, { updateHash: false });
    customElements.whenDefined("plainnvr-live-player").then(() => {
      if (activePage === "live") renderLiveWall();
    });

    render();
  }

  window.plainNvrUi = {
    render,
    navigate,
    stopWallPlayers,
  };

  document.addEventListener("DOMContentLoaded", init);
})();
