import unittest
from unittest import mock

from app.onvif_client import (
    OnvifError,
    allowed_endpoint_hosts,
    cacheable_discovery,
    device_url_candidates,
    parse_device_information,
    parse_profiles,
    parse_service_addresses,
    parse_ptz_features,
    parse_presets,
    redact_url,
    select_profile,
    soap_post,
    validated_onvif_url,
    wsse_password_digest,
)


class OnvifParsingTests(unittest.TestCase):
    def test_parses_device_information(self):
        data = b"""<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
          <s:Body><GetDeviceInformationResponse>
            <Manufacturer>Example</Manufacturer><Model>PTZ-1</Model>
            <FirmwareVersion>2.3.4</FirmwareVersion><SerialNumber>abc</SerialNumber>
            <HardwareId>rev-b</HardwareId>
          </GetDeviceInformationResponse></s:Body></s:Envelope>"""
        self.assertEqual(
            parse_device_information(data),
            {
                "manufacturer": "Example",
                "model": "PTZ-1",
                "firmware_version": "2.3.4",
                "serial_number": "abc",
                "hardware_id": "rev-b",
            },
        )

    def test_parses_profiles_and_selects_ptz_profile(self):
        data = b"""<Envelope><Body><GetProfilesResponse>
          <Profiles token="main"><Name>Main</Name>
            <VideoEncoderConfiguration><Encoding>H264</Encoding>
              <Resolution><Width>1920</Width><Height>1080</Height></Resolution>
            </VideoEncoderConfiguration>
          </Profiles>
          <Profiles token="ptz"><Name>PTZ Profile</Name>
            <PTZConfiguration token="ptz-config">
              <DefaultContinuousPanTiltVelocitySpace>continuous</DefaultContinuousPanTiltVelocitySpace>
            </PTZConfiguration>
          </Profiles>
        </GetProfilesResponse></Body></Envelope>"""
        profiles = parse_profiles(data)
        self.assertEqual(len(profiles), 2)
        self.assertEqual(profiles[0]["video"]["width"], 1920)
        self.assertEqual(select_profile(profiles)["token"], "ptz")
        self.assertEqual(select_profile(profiles, "Main")["token"], "main")

    def test_detects_ptz_features_and_presets(self):
        capabilities = b"""<Envelope><Body><Capabilities MoveStatus="true"/>
        </Body></Envelope>"""
        options = b"""<Envelope><Body><Spaces>
          <ContinuousPanTiltVelocitySpace><Space><URI>continuous</URI></Space></ContinuousPanTiltVelocitySpace>
          <ContinuousZoomVelocitySpace><Space><URI>zoom</URI></Space></ContinuousZoomVelocitySpace>
          <RelativePanTiltTranslationSpace><Space><URI>TranslationSpaceFov</URI></Space></RelativePanTiltTranslationSpace>
        </Spaces></Body></Envelope>"""
        nodes = b"""<Envelope><Body><PTZNode token="node-1">
          <HomeSupported>true</HomeSupported>
        </PTZNode></Body></Envelope>"""
        profile = {"default_spaces": {}}
        features = parse_ptz_features(capabilities, options, profile, nodes)
        self.assertEqual(
            features,
            ["pt", "zoom", "pt-r", "pt-r-fov", "move-status", "home"],
        )
        presets = parse_presets(
            b"""<Envelope><Body><Preset token="1"><Name>Door</Name></Preset></Body></Envelope>"""
        )
        self.assertEqual(presets, [{"name": "Door", "token": "1"}])

    def test_candidates_and_reports_do_not_leak_credentials(self):
        payload = {
            "rtsp_url": "rtsp://user:secret@192.168.1.50:554/stream",
            "ptz_url": "",
        }
        candidates = device_url_candidates(payload)
        self.assertIn("http://192.168.1.50/onvif/device_service", candidates)
        self.assertEqual(
            redact_url(payload["rtsp_url"]),
            "rtsp://<credentials>@192.168.1.50:554/stream",
        )
        cached = cacheable_discovery(
            {
                "profiles": [
                    {
                        "token": "main",
                        "stream_uri": payload["rtsp_url"],
                        "stream_uri_redacted": redact_url(payload["rtsp_url"]),
                    }
                ],
                "endpoint_attempts": [{"endpoint": "x"}],
            }
        )
        self.assertNotIn("stream_uri", cached["profiles"][0])
        self.assertNotIn("endpoint_attempts", cached)

    def test_validated_onvif_urls_stay_on_configured_camera_host(self):
        payload = {
            "rtsp_url": "rtsp://user:secret@192.168.1.50:554/stream",
            "ptz_url": "",
        }
        allowed = allowed_endpoint_hosts(payload)
        self.assertEqual(
            validated_onvif_url(
                "http://user:secret@192.168.1.50/onvif/device_service",
                allowed_hosts=allowed,
            ),
            "http://192.168.1.50/onvif/device_service",
        )

        with self.assertRaises(OnvifError):
            validated_onvif_url(
                "http://192.168.1.51/onvif/device_service",
                allowed_hosts=allowed,
            )
        with self.assertRaises(OnvifError):
            validated_onvif_url("http://127.0.0.1/onvif/device_service")

    def test_service_discovery_ignores_untrusted_xaddrs(self):
        data = b"""<Envelope><Body><GetCapabilitiesResponse>
          <Device><XAddr>http://192.168.1.50/onvif/device_service</XAddr></Device>
          <Media><XAddr>http://127.0.0.1/admin</XAddr></Media>
          <PTZ><XAddr>http://192.168.1.51/onvif/ptz_service</XAddr></PTZ>
        </GetCapabilitiesResponse></Body></Envelope>"""
        services = parse_service_addresses(data, allowed_hosts={"192.168.1.50"})
        self.assertEqual(
            services,
            {"device": "http://192.168.1.50/onvif/device_service"},
        )

    def test_wsse_password_digest_matches_onvif_wire_format(self):
        digest = wsse_password_digest(
            b"\x01\x02\x03\x04",
            "2026-07-22T15:00:00Z",
            "camera-secret",
        )

        self.assertEqual(digest, "MuJp+1aWEtAhLy+dM1EOi9N/Rx0=")

    def test_blocked_onvif_url_is_rejected_before_request_is_built(self):
        with mock.patch("app.onvif_client.urllib_request.Request") as request:
            with self.assertRaises(OnvifError):
                soap_post(
                    "http://127.0.0.1/onvif/device_service",
                    "<tds:GetDeviceInformation/>",
                )

        request.assert_not_called()

    def test_metadata_service_onvif_url_is_rejected(self):
        with self.assertRaises(OnvifError):
            validated_onvif_url("http://169.254.169.254/latest/meta-data")


if __name__ == "__main__":
    unittest.main()
