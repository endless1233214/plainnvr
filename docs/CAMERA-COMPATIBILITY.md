# Camera Compatibility

PlainNVR treats camera support as measured behavior, not a brand-level guess.
Use the downloadable report from the camera editor to capture the exact model,
firmware, stream codecs, ONVIF profiles, and PTZ features that were tested.

## Support Levels

| Level | Meaning |
| --- | --- |
| Verified | Stream, recording, live view, reconnect, and every listed PTZ feature were tested on the named firmware. |
| Stream verified | Live view and recording were tested; PTZ is absent or untested. |
| Reported | A compatibility report was submitted, but maintainers have not reproduced the result. |
| Partial | The report documents a specific failure or required workaround. |

## Published Matrix

Each entry must include a firmware version. Use a separate row for every
materially different firmware branch.

| Manufacturer | Model | Firmware | Level | Video | Audio | ONVIF profiles | PTZ | Presets | Notes | Report |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| _No verified reports published yet_ |  |  |  |  |  |  |  |  |  |  |

## Verification Procedure

1. Add the camera with its main stream URL and run **Test Stream**.
2. Run **Discover ONVIF** and confirm the reported manufacturer, model, and firmware.
3. Select each useful discovered profile and confirm its stream opens.
4. Confirm recording continues while the web live view and iPhone app are open.
5. Confirm the web viewer reports `go2rtc / MSE` when supported.
6. Hold every advertised pan, tilt, and hardware zoom control, then confirm movement stops on release.
7. Test home and every returned preset.
8. Restart the camera and PlainNVR, then repeat live view and one PTZ command.
9. Download the compatibility report and attach it to the matrix entry or issue.

Reports redact configured credentials. Review free-form camera error messages
before publishing because unusual vendor firmware can echo private values.

## Submit A Result

1. Complete the verification procedure for the exact model and firmware.
2. Download the compatibility report from the saved camera.
3. Inspect the JSON for unexpected private data, especially vendor error text.
4. Open an issue or pull request with the model, firmware, support level, test
   notes, and report.

Reports that cannot be reproduced can still be listed as **Reported**. A model
should move to **Verified** only after every advertised feature has been tested
on the named firmware.

## ONVIF Feature Contract

PlainNVR currently records these discovered features:

| Feature | PlainNVR behavior |
| --- | --- |
| `pt` | Continuous pan and tilt controls |
| `zoom` | Continuous hardware zoom |
| `pt-r` | Relative pan/tilt detected for future tracking work |
| `zoom-r` | Relative zoom detected |
| `zoom-a` | Absolute zoom detected |
| `pt-r-fov` | Field-of-view relative movement; autotracking candidate |
| `move-status` | Camera reports movement status; autotracking candidate |
| `home` | Home-position button |
| `presets` | Preset selector |

Autotracking is not enabled merely because a camera is a candidate. It needs a
separate control loop, calibration, and safety limits.

## Vendor Driver Policy

Add a vendor driver only when a report demonstrates that:

1. The camera's current firmware cannot perform the operation through ONVIF.
2. The vendor protocol is stable enough to identify and stop movement safely.
3. The driver has a specific model/firmware scope and does not masquerade as a
   generic implementation.
4. Stream and ONVIF discovery continue to work independently of the vendor PTZ
   path.

The Victure direct-stepper and DVRIP drivers remain explicit fallbacks; they are
not selected automatically for unrelated cameras.
