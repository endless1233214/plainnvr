import json
import unittest
from unittest.mock import Mock

from app import http_api
from test_live_streaming import CapturedHandler


class AppEventTests(unittest.TestCase):
    def test_motion_event_is_forwarded_as_a_plainnvr_event(self):
        handler = CapturedHandler()
        app = Mock()
        app.get_camera.return_value = {"id": "a" * 32}

        http_api.handle_app_event(
            handler,
            app,
            {
                "camera_id": "a" * 32,
                "event_type": "motion",
                "state": "start",
                "confidence": 0.8,
                "source": "motion-basic",
            },
        )

        self.assertEqual(handler.status, 200)
        self.assertEqual(json.loads(handler.wfile.getvalue()), {"ok": True})
        app.add_event.assert_called_once_with(
            "a" * 32,
            "info",
            "motion-basic: motion start (0.80)",
        )

    def test_app_event_rejects_unknown_event_types(self):
        handler = CapturedHandler()
        app = Mock()

        http_api.handle_app_event(
            handler,
            app,
            {"camera_id": "a" * 32, "event_type": "door"},
        )

        self.assertEqual(handler.status, 400)
        app.add_event.assert_not_called()
