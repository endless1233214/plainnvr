package com.plainnvr.companion;

import android.app.Activity;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.media3.common.MediaItem;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.ui.PlayerView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.Locale;

/** Native, server-hosted companion: no camera credentials or recordings are stored on device. */
public final class MainActivity extends Activity {
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private LinearLayout page;
    private PlainNvrApi api;
    private JSONObject status;
    private JSONObject selectedCamera;
    private String tab = "Cameras";
    private ExoPlayer player;
    private EditText serverField;
    private EditText usernameField;
    private EditText passwordField;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        String address = getPreferences(MODE_PRIVATE).getString("server", "");
        if (address.isEmpty()) { showConnection(); return; }
        try { api = new PlainNvrApi(address); }
        catch (IllegalArgumentException error) { showConnection(); return; }
        perform(() -> api.get("/api/auth/state"), auth -> {
            if (auth.optBoolean("authenticated")) refresh();
            else showLogin(auth.optBoolean("setup_required"));
        });
    }

    private interface Request { JSONObject run() throws Exception; }
    private interface Success { void accept(JSONObject value); }

    private void perform(Request request, Success success) {
        network.execute(() -> {
            try {
                JSONObject result = request.run();
                runOnUiThread(() -> success.accept(result));
            } catch (Exception error) {
                runOnUiThread(() -> message(error.getMessage() == null ? "Request failed" : error.getMessage()));
            }
        });
    }

    private void message(String text) { Toast.makeText(this, text, Toast.LENGTH_LONG).show(); }

    private void resetPage(String title) {
        if (player != null) { player.release(); player = null; }
        ScrollView scroll = new ScrollView(this);
        page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(dp(18), dp(24), dp(18), dp(24));
        scroll.addView(page);
        setContentView(scroll);
        TextView heading = label(title, 27);
        heading.setPadding(0, 0, 0, dp(16));
        page.addView(heading);
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private TextView label(String text, int sp) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(sp);
        view.setPadding(0, dp(5), 0, dp(5));
        return view;
    }

    private EditText input(String hint, String value) {
        EditText edit = new EditText(this);
        edit.setSingleLine(true);
        edit.setHint(hint);
        edit.setText(value);
        page.addView(edit, new LinearLayout.LayoutParams(-1, dp(54)));
        return edit;
    }

    private Button button(String text, Runnable action) {
        Button view = new Button(this);
        view.setText(text);
        view.setAllCaps(false);
        view.setOnClickListener(v -> action.run());
        page.addView(view, new LinearLayout.LayoutParams(-1, dp(52)));
        return view;
    }

    private void note(String text) { page.addView(label(text, 15)); }

    private void gap() { View view = new View(this); page.addView(view, new LinearLayout.LayoutParams(1, dp(16))); }

    private void showConnection() {
        resetPage("Connect to PlainNVR");
        note("Enter the address of your own PlainNVR server. Use HTTPS when connecting outside a trusted local network.");
        serverField = input("https://nvr.example.com or http://192.168.1.x:8787",
                getPreferences(MODE_PRIVATE).getString("server", ""));
        button("Connect", () -> {
            try { api = new PlainNvrApi(serverField.getText().toString()); }
            catch (IllegalArgumentException error) { message(error.getMessage()); return; }
            if (api.origin().startsWith("http://"))
                message("HTTP is unencrypted. Use it only on a trusted local network.");
            perform(() -> api.get("/api/auth/state"), auth -> {
                getPreferences(MODE_PRIVATE).edit().putString("server", api.origin()).apply();
                if (auth.optBoolean("authenticated")) refresh();
                else showLogin(auth.optBoolean("setup_required"));
            });
        });
    }

    private void showLogin(boolean setup) {
        resetPage(setup ? "Create PlainNVR admin" : "Sign in to PlainNVR");
        note(api.origin());
        usernameField = input("Username", getPreferences(MODE_PRIVATE).getString("username", ""));
        passwordField = input("Password", "");
        passwordField.setInputType(0x81);
        button(setup ? "Create admin" : "Sign in", () -> {
            String username = usernameField.getText().toString().trim();
            String password = passwordField.getText().toString();
            if (username.isEmpty() || password.isEmpty()) { message("Enter username and password."); return; }
            perform(() -> api.post(setup ? "/api/auth/setup" : "/api/auth/login",
                    new JSONObject().put("username", username).put("password", password)), value -> {
                passwordField.setText("");
                getPreferences(MODE_PRIVATE).edit().putString("username", username).apply();
                refresh();
            });
        });
        button("Change server", this::showConnection);
    }

    private void refresh() {
        perform(() -> api.get("/api/status"), value -> { status = value; render(); });
    }

    private JSONArray cameras() { return status == null ? new JSONArray() : status.optJSONArray("cameras"); }

    private JSONObject cameraAt(int index) { return cameras().optJSONObject(index); }

    private void navigation() {
        HorizontalScrollView scroll = new HorizontalScrollView(this);
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        for (String name : new String[]{"Cameras", "Live", "Recordings", "Events", "Settings"}) {
            Button item = new Button(this);
            item.setText((name.equals(tab) ? "● " : "") + name);
            item.setAllCaps(false);
            item.setOnClickListener(v -> { tab = name; render(); });
            row.addView(item);
        }
        scroll.addView(row);
        page.addView(scroll);
        gap();
    }

    private void cameraPicker(Runnable onChange) {
        JSONArray all = cameras();
        if (all == null || all.length() == 0) { note("No cameras are configured on this server."); return; }
        for (int index = 0; index < all.length(); index++) {
            JSONObject camera = cameraAt(index);
            if (camera == null) continue;
            button((selectedCamera != null && camera.optString("id").equals(selectedCamera.optString("id")) ? "● " : "")
                    + camera.optString("name", "Camera"), () -> { selectedCamera = camera; onChange.run(); });
        }
        if (selectedCamera == null) selectedCamera = cameraAt(0);
        gap();
    }

    private void render() {
        if (status == null) { showConnection(); return; }
        resetPage("PlainNVR");
        navigation();
        switch (tab) {
            case "Live": showLive(); break;
            case "Recordings": showRecordings(); break;
            case "Events": showEvents(); break;
            case "Settings": showSettings(); break;
            default: showCameras();
        }
    }

    private void showCameras() {
        note("Cameras");
        JSONArray all = cameras();
        if (all == null || all.length() == 0) { note("No cameras configured."); return; }
        JSONObject recorders = status.optJSONObject("recorders");
        for (int index = 0; index < all.length(); index++) {
            JSONObject camera = cameraAt(index);
            if (camera == null) continue;
            gap();
            page.addView(label(camera.optString("name", "Camera"), 21));
            note(camera.optBoolean("enabled") ? "Enabled" : "Disabled");
            JSONObject recorder = recorders == null ? null : recorders.optJSONObject(camera.optString("id"));
            if (recorder != null) note(recorder.optBoolean("paused") ? "Recorder paused" :
                    recorder.optBoolean("running") ? "Recording" : "Recorder stopped");
            button("View live", () -> { selectedCamera = camera; tab = "Live"; render(); });
            button("Browse recordings", () -> { selectedCamera = camera; tab = "Recordings"; render(); });
            button("Stop recorder", () -> control(camera, "stop"));
            if (camera.optBoolean("enabled")) {
                button("Start recorder", () -> control(camera, "start"));
                button("Restart recorder", () -> control(camera, "restart"));
            }
        }
    }

    private void control(JSONObject camera, String action) {
        String id = camera.optString("id");
        perform(() -> api.post("/api/cameras/" + id + "/recorder/" + action, new JSONObject()),
                value -> { message("Recorder " + action + " requested"); refresh(); });
    }

    private void showLive() {
        note("Live view (HLS)");
        cameraPicker(this::render);
        if (selectedCamera == null) return;
        String id = selectedCamera.optString("id");
        String token = status.optString("stream_token", "");
        PlayerView view = new PlayerView(this);
        view.setMinimumHeight(dp(230));
        view.setLayoutParams(new LinearLayout.LayoutParams(-1, dp(260)));
        page.addView(view);
        player = new ExoPlayer.Builder(this).build();
        view.setPlayer(player);
        player.setMediaItem(MediaItem.fromUri(api.url(PlainNvrApi.livePath(id, token))));
        player.prepare();
        player.play();
        button("Reload live view", this::render);
        if (selectedCamera.optBoolean("ptz_enabled")) showPtz(selectedCamera);
    }

    private void showPtz(JSONObject camera) {
        gap();
        page.addView(label("PTZ", 21));
        JSONArray features = camera.optJSONArray("ptz_features");
        boolean supportsPanTilt = features == null || features.length() == 0 || contains(features, "pt");
        if (supportsPanTilt) {
            for (String action : new String[]{"up", "left", "right", "down", "stop"})
                button(action.substring(0, 1).toUpperCase(Locale.ROOT) + action.substring(1),
                        () -> ptz(camera, action, null));
        }
        if (!"victure_direct".equals(camera.optString("ptz_type"))
                && (features == null || features.length() == 0 || contains(features, "zoom"))) {
            button("Zoom in", () -> ptz(camera, "zoom_in", null));
            button("Zoom out", () -> ptz(camera, "zoom_out", null));
        }
        if (!"victure_direct".equals(camera.optString("ptz_type"))
                && (features == null || features.length() == 0 || contains(features, "home")))
            button("Home", () -> ptz(camera, "home", null));
        JSONArray presets = camera.optJSONArray("ptz_presets");
        if (presets != null) for (int index = 0; index < presets.length(); index++) {
            JSONObject preset = presets.optJSONObject(index);
            if (preset != null) button("Preset: " + preset.optString("name"),
                    () -> ptz(camera, "preset", preset.optString("token")));
        }
    }

    private static boolean contains(JSONArray array, String value) {
        for (int index = 0; index < array.length(); index++) if (value.equals(array.optString(index))) return true;
        return false;
    }

    private void ptz(JSONObject camera, String action, String preset) {
        perform(() -> {
            JSONObject body = new JSONObject().put("action", action)
                    .put("speed", camera.optDouble("ptz_speed", 0.5)).put("duration_ms", 300);
            if (preset != null) body.put("preset_token", preset);
            return api.post("/api/cameras/" + camera.optString("id") + "/ptz", body);
        }, value -> message("PTZ " + action + " sent"));
    }

    private void showRecordings() {
        note("Recordings");
        cameraPicker(this::render);
        if (selectedCamera == null) return;
        String id = selectedCamera.optString("id");
        perform(() -> api.get(PlainNvrApi.coveragePath(id)), value -> {
            if (!"Recordings".equals(tab) || selectedCamera == null
                    || !id.equals(selectedCamera.optString("id"))) return;
            JSONObject coverage = value.optJSONObject("coverage");
            if (coverage == null) return;
            note(coverage.optInt("count") + " clips");
            JSONArray dates = coverage.optJSONArray("dates");
            if (dates == null || dates.length() == 0) { note("No recordings yet."); return; }
            for (int index = dates.length() - 1; index >= 0; index--) {
                String date = dates.optString(index);
                button(date, () -> showSegments(id, date));
            }
        });
    }

    private void showSegments(String id, String date) {
        perform(() -> api.get(PlainNvrApi.segmentsPath(id, date)), value -> {
            if (!"Recordings".equals(tab) || selectedCamera == null
                    || !id.equals(selectedCamera.optString("id"))) return;
            gap();
            page.addView(label(date + " clips", 21));
            JSONArray clips = value.optJSONArray("segments");
            if (clips == null || clips.length() == 0) { note("No clips on this date."); return; }
            for (int index = 0; index < clips.length(); index++) {
                JSONObject clip = clips.optJSONObject(index);
                if (clip == null) continue;
                String path = clip.optString("url");
                button(clip.optString("start") + " • " + clip.optString("filename"),
                        () -> playClip(path));
            }
        });
    }

    private void playClip(String path) {
        String token = status.optString("stream_token", "");
        if (!path.startsWith("/media/")) { message("Invalid recording path."); return; }
        if (player != null) player.release();
        PlayerView view = new PlayerView(this);
        view.setLayoutParams(new LinearLayout.LayoutParams(-1, dp(260)));
        page.addView(view);
        player = new ExoPlayer.Builder(this).build();
        view.setPlayer(player);
        player.setMediaItem(MediaItem.fromUri(api.url(PlainNvrApi.mediaPath(path, token))));
        player.prepare();
        player.play();
    }

    private void showEvents() {
        note("Recent recorder and app events");
        JSONArray events = status.optJSONArray("events");
        if (events == null || events.length() == 0) { note("No recent events."); return; }
        for (int index = events.length() - 1; index >= 0; index--) {
            JSONObject event = events.optJSONObject(index);
            if (event != null) {
                gap();
                note(event.optString("created_at") + " • " + event.optString("level"));
                page.addView(label(event.optString("message"), 18));
            }
        }
        button("Refresh events", this::refresh);
    }

    private void showSettings() {
        note("Server: " + api.origin());
        note("User: " + status.optString("username", ""));
        note("This app stores only the server address and username. The session cookie stays in memory; the password is not saved.");
        button("Refresh", this::refresh);
        button("Sign out", () -> perform(() -> api.post("/api/auth/logout", new JSONObject()), value -> {
            status = null;
            showLogin(false);
        }));
        button("Change server", () -> { status = null; showConnection(); });
    }

    @Override protected void onDestroy() {
        if (player != null) player.release();
        network.shutdownNow();
        super.onDestroy();
    }

    @Override protected void onStop() {
        if (player != null) player.pause();
        super.onStop();
    }
}
