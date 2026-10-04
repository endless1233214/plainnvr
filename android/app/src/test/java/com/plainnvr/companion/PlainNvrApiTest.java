package com.plainnvr.companion;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

public final class PlainNvrApiTest {
    @Test public void normalizesServerWithoutKeepingPathsOrCredentials() {
        assertEquals("http://192.168.1.4:8787", new PlainNvrApi("192.168.1.4:8787/").origin());
        assertEquals("https://nvr.example", new PlainNvrApi("https://nvr.example").origin());
        assertThrows(IllegalArgumentException.class, () -> new PlainNvrApi("https://user:pass@nvr.example"));
        assertThrows(IllegalArgumentException.class, () -> new PlainNvrApi("https://nvr.example/other"));
    }

    @Test public void usesExistingCoverageSegmentsAndLivePaths() {
        assertEquals("/api/coverage?camera_id=a%20b", PlainNvrApi.coveragePath("a b"));
        assertEquals("/api/segments?camera_id=abc&date=2026-10-03",
                PlainNvrApi.segmentsPath("abc", "2026-10-03"));
        assertTrue(PlainNvrApi.livePath("abc", "secret/&")
                .startsWith("/live/abc/stream.m3u8?reload="));
        assertTrue(PlainNvrApi.livePath("abc", "secret/&").endsWith("&token=secret%2F%26"));
        assertEquals("/media/abc/file.mp4?token=x%20y",
                PlainNvrApi.mediaPath("/media/abc/file.mp4", "x y"));
    }
}
