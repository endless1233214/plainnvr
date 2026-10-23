package com.plainnvr.companion;

import androidx.test.ext.junit.runners.AndroidJUnit4;

import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

@RunWith(AndroidJUnit4.class)
public final class PlainNvrApiDeviceTest {
    @Test public void authenticatesAndReusesSessionCookieOnDevice() throws Exception {
        ExecutorService serverThread = Executors.newSingleThreadExecutor();
        try (ServerSocket listener = new ServerSocket(0, 3, InetAddress.getByName("127.0.0.1"))) {
            listener.setSoTimeout(15000);
            Future<?> server = serverThread.submit(() -> {
                try {
                    serve(listener, "GET /api/auth/state ", false,
                            "{\"authenticated\":false,\"setup_required\":false}", false);
                    serve(listener, "POST /api/auth/login ", false,
                            "{\"ok\":true,\"username\":\"test-admin\"}", true);
                    serve(listener, "GET /api/status ", true,
                            "{\"cameras\":[],\"events\":[],\"username\":\"test-admin\"}", false);
                } catch (Exception error) {
                    throw new RuntimeException(error);
                }
            });

            PlainNvrApi api = new PlainNvrApi("http://127.0.0.1:" + listener.getLocalPort());
            assertFalse(api.get("/api/auth/state").getBoolean("authenticated"));
            assertTrue(api.post("/api/auth/login", new JSONObject()
                    .put("username", "test-admin").put("password", "disposable-test-password"))
                    .getBoolean("ok"));
            assertEquals("test-admin", api.get("/api/status").getString("username"));
            server.get(20, TimeUnit.SECONDS);
        } finally {
            serverThread.shutdownNow();
        }
    }

    private static void serve(ServerSocket listener, String expectedRequest, boolean requireCookie,
                              String body, boolean setCookie) throws Exception {
        try (Socket socket = listener.accept()) {
            socket.setSoTimeout(10000);
            BufferedReader reader = new BufferedReader(new InputStreamReader(
                    socket.getInputStream(), StandardCharsets.UTF_8));
            String request = reader.readLine();
            assertTrue(request, request != null && request.startsWith(expectedRequest));
            boolean cookieSeen = false;
            int contentLength = 0;
            String header;
            while ((header = reader.readLine()) != null && !header.isEmpty()) {
                if (header.regionMatches(true, 0, "Cookie:", 0, 7)
                        && header.contains("plainnvr_test_session=fixture")) cookieSeen = true;
                if (header.regionMatches(true, 0, "Content-Length:", 0, 15))
                    contentLength = Integer.parseInt(header.substring(15).trim());
            }
            if (requireCookie) assertTrue("Login cookie was not sent", cookieSeen);
            for (int i = 0; i < contentLength; i++) reader.read();
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            String response = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                    + bytes.length + "\r\nConnection: close\r\n"
                    + (setCookie ? "Set-Cookie: plainnvr_test_session=fixture; HttpOnly; Path=/\r\n" : "")
                    + "\r\n";
            OutputStream output = socket.getOutputStream();
            output.write(response.getBytes(StandardCharsets.US_ASCII));
            output.write(bytes);
            output.flush();
        }
    }
}
