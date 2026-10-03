import json
import subprocess
import unittest
from unittest import mock

from app import tapo_control


class TapoControlTests(unittest.TestCase):
    def camera(self, **overrides):
        return {
            "id": "camera-id",
            "rtsp_url": (
                "rtsp://stream-user:stream-pass@"
                "192.168.1.199:554/stream1"
            ),
            "tapo_enabled": True,
            "tapo_host": "",
            "tapo_username": "account@example.test",
            "tapo_password": "control-secret",
            **overrides,
        }

    @mock.patch.object(tapo_control.subprocess, "run")
    def test_secret_is_sent_over_stdin_not_argv(self, run):
        run.return_value = subprocess.CompletedProcess(
            ["plainnvr-tapoctl"],
            0,
            b'{"ok":true,"transport":"tpap"}',
            b"",
        )
        result = tapo_control.control_request(
            self.camera(),
            "probe",
        )
        self.assertTrue(result["ok"])
        args, kwargs = run.call_args
        self.assertNotIn("control-secret", args[0])
        request = json.loads(kwargs["input"])
        self.assertEqual(request["host"], "192.168.1.199")
        self.assertEqual(
            request["password"],
            "control-secret",
        )
        self.assertFalse(kwargs["check"])

    @mock.patch.object(tapo_control.subprocess, "run")
    def test_stream_credentials_are_the_legacy_fallback(self, run):
        run.return_value = subprocess.CompletedProcess(
            ["plainnvr-tapoctl"],
            0,
            b'{"ok":true}',
            b"",
        )
        tapo_control.control_request(
            self.camera(
                tapo_username="",
                tapo_password="",
            ),
            "state",
        )
        request = json.loads(
            run.call_args.kwargs["input"]
        )
        self.assertEqual(
            request["username"],
            "stream-user",
        )
        self.assertEqual(
            request["password"],
            "stream-pass",
        )

    @mock.patch.object(tapo_control.subprocess, "run")
    def test_public_address_is_rejected_before_helper(self, run):
        with self.assertRaisesRegex(
            ValueError,
            "local IP",
        ):
            tapo_control.control_request(
                self.camera(tapo_host="8.8.8.8"),
                "probe",
            )
        run.assert_not_called()

    @mock.patch.object(tapo_control.subprocess, "run")
    def test_unknown_control_is_rejected_before_helper(self, run):
        with self.assertRaisesRegex(
            ValueError,
            "Unsupported Tapo control",
        ):
            tapo_control.control_request(
                self.camera(),
                "set",
                "raw_rpc",
                {},
            )
        run.assert_not_called()

    @mock.patch.object(tapo_control.subprocess, "run")
    def test_helper_error_redacts_credentials(self, run):
        run.return_value = subprocess.CompletedProcess(
            ["plainnvr-tapoctl"],
            1,
            (
                b'{"ok":false,"error":'
                b'"control-secret was rejected"}'
            ),
            b"",
        )
        with self.assertRaisesRegex(
            tapo_control.TapoControlError,
            "<redacted> was rejected",
        ):
            tapo_control.control_request(
                self.camera(),
                "probe",
            )


if __name__ == "__main__":
    unittest.main()
