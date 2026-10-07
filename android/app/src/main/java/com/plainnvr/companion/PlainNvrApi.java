package com.plainnvr.companion;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/** Only endpoints already implemented by PlainNVR's http_api.py are used here. */
final class PlainNvrApi {
    private final String origin;
    private String sessionCookie = "";

    PlainNvrApi(String address) {
        String value = address.trim();
        if (!value.contains("://")) value = "http://" + value;
        URI uri;
        try { uri = URI.create(value); }
        catch (IllegalArgumentException error) { throw new IllegalArgumentException("Invalid PlainNVR server address."); }
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
        if (!("http".equals(scheme) || "https".equals(scheme))
                || uri.getHost() == null || uri.getHost().isEmpty()
                || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null
                || (uri.getPath() != null && !uri.getPath().isEmpty() && !"/".equals(uri.getPath()))) {
            throw new IllegalArgumentException("Enter a PlainNVR server address, without a path or credentials.");
        }
        origin = scheme + "://" + uri.getRawAuthority();
    }

    String origin() { return origin; }

    String url(String path) { return origin + path; }

    JSONObject get(String path) throws IOException, JSONException { return request("GET", path, null); }
    JSONObject post(String path, JSONObject body) throws IOException, JSONException { return request("POST", path, body); }

    JSONObject request(String method, String path, JSONObject body) throws IOException, JSONException {
        HttpURLConnection connection = (HttpURLConnection) new URL(url(path)).openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(12000);
        connection.setReadTimeout(30000);
        connection.setRequestProperty("Accept", "application/json");
        connection.setUseCaches(false);
        if (!sessionCookie.isEmpty()) connection.setRequestProperty("Cookie", sessionCookie);
        if (body != null) {
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
            connection.getOutputStream().write(bytes);
        }
        try {
            int code = connection.getResponseCode();
            String setCookie = connection.getHeaderField("Set-Cookie");
            if (setCookie != null) {
                int semicolon = setCookie.indexOf(';');
                String pair = (semicolon < 0 ? setCookie : setCookie.substring(0, semicolon)).trim();
                int equals = pair.indexOf('=');
                sessionCookie = equals >= 0 && equals == pair.length() - 1 ? "" : pair;
            }
            InputStream stream = code >= 400 ? connection.getErrorStream() : connection.getInputStream();
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            if (stream != null) {
                byte[] buffer = new byte[8192];
                int count;
                while ((count = stream.read(buffer)) != -1) output.write(buffer, 0, count);
                stream.close();
            }
            String response = new String(output.toByteArray(), StandardCharsets.UTF_8);
            JSONObject json = response.isEmpty() ? new JSONObject() : new JSONObject(response);
            if (code < 200 || code >= 300) {
                throw new IOException(json.optString("error", "PlainNVR returned HTTP " + code));
            }
            return json;
        } finally {
            connection.disconnect();
        }
    }

    static String coveragePath(String cameraId) {
        return "/api/coverage?camera_id=" + encode(cameraId);
    }

    static String segmentsPath(String cameraId, String date) {
        return "/api/segments?camera_id=" + encode(cameraId) + "&date=" + encode(date);
    }

    static String livePath(String cameraId, String token) {
        return "/live/" + encode(cameraId) + "/stream.m3u8?reload="
                + System.currentTimeMillis() + (token.isEmpty() ? "" : "&token=" + encode(token));
    }

    static String mediaPath(String path, String token) {
        return path + (token.isEmpty() ? "" : (path.contains("?") ? "&" : "?") + "token=" + encode(token));
    }

    private static String encode(String value) {
        StringBuilder result = new StringBuilder();
        for (byte item : value.getBytes(StandardCharsets.UTF_8)) {
            int code = item & 0xff;
            if ((code >= 'A' && code <= 'Z') || (code >= 'a' && code <= 'z')
                    || (code >= '0' && code <= '9') || code == '-' || code == '_' || code == '.' || code == '~') {
                result.append((char) code);
            } else {
                result.append('%');
                result.append(Character.toUpperCase(Character.forDigit(code >>> 4, 16)));
                result.append(Character.toUpperCase(Character.forDigit(code & 15, 16)));
            }
        }
        return result.toString();
    }
}
