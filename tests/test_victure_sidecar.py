import json
import os
import tempfile
import unittest
from unittest import mock

from app import victure_sidecar


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self, _limit):
        return b'{"ok":true,"driver":"victure_direct"}'


class VictureSidecarTests(unittest.TestCase):
    def test_request_has_only_required_camera_fields_and_token(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as secret:
            secret.write("a" * 40)
            path = secret.name
        try:
            with mock.patch.dict(os.environ, {
                "NVR_VICTURE_DRIVER_URL": "http://victure-driver:8795",
                "NVR_VICTURE_DRIVER_TOKEN_FILE": path,
            }), mock.patch.object(victure_sidecar.request, "urlopen", return_value=Response()) as send:
                result = victure_sidecar.call("ptz", {
                    "ptz_type": "victure_direct", "rtsp_url": "rtsp://192.168.1.2/live",
                    "id": "must-not-leave-core", "ptz_url": "http://192.168.1.2:8088",
                }, action="left", speed=0.5)
            self.assertTrue(result["ok"])
            outgoing = send.call_args.args[0]
            body = json.loads(outgoing.data)
            self.assertEqual(body["mode"], "victure_direct")
            self.assertNotIn("id", body["camera"])
            self.assertEqual(outgoing.get_header("Authorization"), "Bearer " + "a" * 40)
        finally:
            os.unlink(path)

    def test_missing_token_or_invalid_url_blocks_request(self):
        with mock.patch.dict(os.environ, {
            "NVR_VICTURE_DRIVER_URL": "https://public.example",
            "NVR_VICTURE_DRIVER_TOKEN_FILE": "",
        }):
            with self.assertRaises(RuntimeError):
                victure_sidecar.call("ptz", {"ptz_type": "victure_direct"})


if __name__ == "__main__":
    unittest.main()
