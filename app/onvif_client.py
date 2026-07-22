import base64
import hashlib
from html import escape as html_escape
import ipaddress
import re
import secrets
import socket
from datetime import datetime, timezone
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote, unquote, urlparse, urlunparse
from xml.etree import ElementTree


DEVICE_NS = "http://www.onvif.org/ver10/device/wsdl"
MEDIA_NS = "http://www.onvif.org/ver10/media/wsdl"
PTZ_NS = "http://www.onvif.org/ver20/ptz/wsdl"
SCHEMA_NS = "http://www.onvif.org/ver10/schema"
SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"

DEVICE_PATHS = ("/onvif/device_service", "/onvif/device", "/onvif/services")
DEVICE_PORTS = (80, 8080, 8000, 8899)
ONVIF_HTTP_SCHEMES = ("http", "https")
BLOCKED_ONVIF_HOSTS = ("localhost",)


class OnvifError(RuntimeError):
    pass


def local_name(tag):
    return str(tag).rsplit("}", 1)[-1]


def first_descendant(element, name):
    if element is None:
        return None
    for child in element.iter():
        if local_name(child.tag) == name:
            return child
    return None


def descendants(element, name):
    if element is None:
        return []
    return [child for child in element.iter() if local_name(child.tag) == name]


def child_text(element, name, default=""):
    child = first_descendant(element, name)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def attr_value(element, name, default=""):
    if element is None:
        return default
    for key, value in element.attrib.items():
        if local_name(key) == name:
            return value
    return default


def bool_value(value):
    return str(value or "").strip().lower() in ("1", "true", "yes")


def parse_xml(data):
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise OnvifError("Camera returned invalid ONVIF XML.") from exc


def credentials_from_url(value):
    parsed = urlparse(str(value or ""))
    if parsed.username is None:
        return None
    return unquote(parsed.username), unquote(parsed.password or "")


def netloc_without_credentials(parsed):
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{parsed.port}" if parsed.port else host


def normalized_host(host):
    return str(host or "").strip().rstrip(".").lower()


def allowed_endpoint_hosts(payload):
    hosts = set()
    for key in ("ptz_url", "rtsp_url"):
        value = str((payload or {}).get(key) or "").strip()
        if not value:
            continue
        parsed = urlparse(value if "://" in value else f"http://{value}")
        if parsed.hostname:
            hosts.add(normalized_host(parsed.hostname))
    return hosts


def _blocked_onvif_ip(address):
    ip = ipaddress.ip_address(address)
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_onvif_host(host):
    normalized = normalized_host(host)
    if not normalized:
        raise OnvifError("ONVIF endpoint must include a host.")
    if normalized in BLOCKED_ONVIF_HOSTS or normalized.endswith(".localhost"):
        raise OnvifError("ONVIF endpoint host is not allowed.")

    try:
        if _blocked_onvif_ip(normalized):
            raise OnvifError("ONVIF endpoint IP address is not allowed.")
        return
    except ValueError:
        pass

    try:
        addresses = socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise OnvifError(f"Could not resolve ONVIF endpoint host: {normalized}") from exc

    for item in addresses:
        address = item[4][0]
        try:
            if _blocked_onvif_ip(address):
                raise OnvifError("ONVIF endpoint resolved to a blocked address.")
        except ValueError:
            raise OnvifError("ONVIF endpoint resolved to an invalid address.")


def validated_onvif_url(value, allowed_hosts=None):
    parsed = urlparse(str(value or ""))
    if parsed.scheme not in ONVIF_HTTP_SCHEMES or not parsed.hostname:
        raise OnvifError("ONVIF endpoint must be an http or https URL.")

    host = normalized_host(parsed.hostname)
    allowed = {normalized_host(item) for item in (allowed_hosts or []) if item}
    if allowed and host not in allowed:
        raise OnvifError("ONVIF endpoint host must match the configured camera host.")

    _validate_onvif_host(host)
    return clean_url(value)


def clean_url(value):
    parsed = urlparse(str(value or ""))
    if not parsed.scheme or not parsed.hostname:
        return str(value or "")
    return urlunparse(
        (
            parsed.scheme,
            netloc_without_credentials(parsed),
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def redact_url(value):
    parsed = urlparse(str(value or ""))
    if not parsed.scheme or not parsed.hostname:
        return str(value or "")
    credentials = "<credentials>@" if parsed.username is not None else ""
    return urlunparse(
        (
            parsed.scheme,
            credentials + netloc_without_credentials(parsed),
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def inject_credentials(value, credentials):
    if not credentials:
        return value
    parsed = urlparse(str(value or ""))
    if not parsed.scheme or not parsed.hostname or parsed.username is not None:
        return value
    username, password = credentials
    userinfo = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    return urlunparse(
        (
            parsed.scheme,
            userinfo + netloc_without_credentials(parsed),
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def fault_message(data):
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        text = data.decode("utf-8", errors="replace")
        return "ONVIF SOAP fault" if re.search(r"<(?:\w+:)?Fault\b", text) else None

    fault = first_descendant(root, "Fault")
    if fault is None:
        return None
    values = [item.text.strip() for item in descendants(fault, "Value") if item.text]
    reasons = [item.text.strip() for item in descendants(fault, "Text") if item.text]
    parts = []
    if values:
        parts.append(values[-1])
    if reasons:
        parts.append(reasons[0])
    return ": ".join(parts) or "ONVIF SOAP fault"


def wsse_password_digest(nonce, created, credential_secret):
    """Return the ONVIF WS-Security UsernameToken wire-format digest."""
    digest_input = nonce + created.encode("utf-8") + credential_secret.encode("utf-8")
    # ONVIF WS-Security UsernameToken PasswordDigest is fixed by spec:
    # Base64(SHA-1(nonce + created + password)). This compatibility digest is
    # sent to the camera for SOAP auth; it is not PlainNVR password storage.
    # codeql[py/weak-sensitive-data-hashing]
    # lgtm[py/weak-sensitive-data-hashing]
    digest = hashlib.sha1(digest_input).digest()
    return base64.b64encode(digest).decode("ascii")


def security_header(credentials, password_mode="digest"):
    if not credentials:
        return ""
    username, credential_secret = credentials
    nonce = secrets.token_bytes(16)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce_text = base64.b64encode(nonce).decode("ascii")
    if password_mode == "text":
        password_type = (
            "http://docs.oasis-open.org/wss/2004/01/"
            "oasis-200401-wss-username-token-profile-1.0#PasswordText"
        )
        password_value = html_escape(credential_secret)
    else:
        password_type = (
            "http://docs.oasis-open.org/wss/2004/01/"
            "oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
        )
        password_value = wsse_password_digest(nonce, created, credential_secret)
    return f"""<s:Header>
    <wsse:Security s:mustUnderstand="1"
      xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
      xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
      <wsse:UsernameToken>
        <wsse:Username>{html_escape(username)}</wsse:Username>
        <wsse:Password Type="{password_type}">{password_value}</wsse:Password>
        <wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{nonce_text}</wsse:Nonce>
        <wsu:Created>{created}</wsu:Created>
      </wsse:UsernameToken>
    </wsse:Security>
  </s:Header>"""


def envelope(body, credentials=None, password_mode="digest"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="{SOAP_NS}" xmlns:tds="{DEVICE_NS}"
  xmlns:trt="{MEDIA_NS}" xmlns:tptz="{PTZ_NS}" xmlns:tt="{SCHEMA_NS}">
  {security_header(credentials, password_mode=password_mode)}
  <s:Body>{body}</s:Body>
</s:Envelope>"""


def _http_open(request, url, credentials, timeout):
    try:
        return urllib_request.urlopen(request, timeout=timeout)
    except urllib_error.HTTPError as exc:
        if exc.code != 401 or not credentials:
            raise
        username, password = credentials
        manager = urllib_request.HTTPPasswordMgrWithDefaultRealm()
        manager.add_password(None, url, username, password)
        opener = urllib_request.build_opener(urllib_request.HTTPDigestAuthHandler(manager))
        return opener.open(request, timeout=timeout)


def validated_onvif_request(safe_url, payload):
    # `safe_url` must come from validated_onvif_url(), which limits ONVIF
    # requests to http(s), the configured camera host, and non-local/meta IPs.
    # codeql[py/full-ssrf]
    # lgtm[py/full-ssrf]
    return urllib_request.Request(
        safe_url,
        data=payload,
        headers={
            "Content-Type": "application/soap+xml; charset=utf-8",
            "Accept": "application/soap+xml, text/xml, */*",
        },
        method="POST",
    )


def soap_post(url, body, credentials=None, timeout=5, allowed_hosts=None):
    first_fault = None
    for password_mode in ("digest", "text"):
        safe_url = validated_onvif_url(url, allowed_hosts=allowed_hosts)
        payload = envelope(body, credentials=credentials, password_mode=password_mode).encode(
            "utf-8"
        )
        request = validated_onvif_request(safe_url, payload)
        if credentials:
            username, password = credentials
            token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode(
                "ascii"
            )
            request.add_header("Authorization", f"Basic {token}")
        try:
            with _http_open(request, safe_url, credentials, timeout) as response:
                data = response.read(256 * 1024)
        except urllib_error.HTTPError as exc:
            detail = exc.read(8192).decode("utf-8", errors="replace").strip()
            raise OnvifError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
        except (TimeoutError, OSError, urllib_error.URLError) as exc:
            raise OnvifError(str(exc)) from exc

        fault = fault_message(data)
        if not fault:
            return data
        if first_fault is None:
            first_fault = fault
    raise OnvifError(first_fault or "ONVIF request failed.")


def device_url_candidates(payload):
    stream_url = str(payload.get("rtsp_url") or "").strip()
    control_url = str(payload.get("ptz_url") or "").strip()
    sources = [value for value in (control_url, stream_url) if value]
    candidates = []

    def add(value):
        value = clean_url(value)
        if value and value not in candidates:
            candidates.append(value)

    for source in sources:
        parsed = urlparse(source if "://" in source else f"http://{source}")
        if not parsed.hostname:
            continue
        scheme = parsed.scheme if parsed.scheme in ("http", "https") else "http"
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if control_url and source == control_url and parsed.path not in ("", "/"):
            if "device" in parsed.path.lower():
                add(source)
            base_port = f":{parsed.port}" if parsed.port else ""
            add(f"{scheme}://{host}{base_port}/onvif/device_service")
        for port in DEVICE_PORTS:
            suffix = "" if (scheme == "http" and port == 80) else f":{port}"
            for path in DEVICE_PATHS:
                add(f"{scheme}://{host}{suffix}{path}")
    return candidates


def payload_credentials(payload):
    return credentials_from_url(payload.get("ptz_url")) or credentials_from_url(
        payload.get("rtsp_url")
    )


def get_device_information_body():
    return "<tds:GetDeviceInformation/>"


def get_capabilities_body():
    return """<tds:GetCapabilities>
      <tds:Category>All</tds:Category>
    </tds:GetCapabilities>"""


def get_profiles_body():
    return "<trt:GetProfiles/>"


def get_stream_uri_body(profile_token):
    token = html_escape(profile_token, quote=True)
    return f"""<trt:GetStreamUri>
      <trt:StreamSetup>
        <tt:Stream>RTP-Unicast</tt:Stream>
        <tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport>
      </trt:StreamSetup>
      <trt:ProfileToken>{token}</trt:ProfileToken>
    </trt:GetStreamUri>"""


def get_ptz_capabilities_body():
    return "<tptz:GetServiceCapabilities/>"


def get_ptz_options_body(configuration_token):
    token = html_escape(configuration_token, quote=True)
    return f"""<tptz:GetConfigurationOptions>
      <tptz:ConfigurationToken>{token}</tptz:ConfigurationToken>
    </tptz:GetConfigurationOptions>"""


def get_ptz_nodes_body():
    return "<tptz:GetNodes/>"


def get_presets_body(profile_token):
    token = html_escape(profile_token, quote=True)
    return f"""<tptz:GetPresets>
      <tptz:ProfileToken>{token}</tptz:ProfileToken>
    </tptz:GetPresets>"""


def goto_preset_body(profile_token, preset_token):
    profile = html_escape(profile_token, quote=True)
    preset = html_escape(preset_token, quote=True)
    return f"""<tptz:GotoPreset>
      <tptz:ProfileToken>{profile}</tptz:ProfileToken>
      <tptz:PresetToken>{preset}</tptz:PresetToken>
    </tptz:GotoPreset>"""


def parse_device_information(data):
    root = parse_xml(data)
    return {
        "manufacturer": child_text(root, "Manufacturer", "Unknown"),
        "model": child_text(root, "Model", "Unknown"),
        "firmware_version": child_text(root, "FirmwareVersion", "Unknown"),
        "serial_number": child_text(root, "SerialNumber", "Unknown"),
        "hardware_id": child_text(root, "HardwareId", "Unknown"),
    }


def parse_service_addresses(data, allowed_hosts=None):
    root = parse_xml(data)
    services = {}
    for service_name in ("Device", "Media", "PTZ", "Imaging", "Events"):
        for element in descendants(root, service_name):
            address = child_text(element, "XAddr")
            if address:
                try:
                    services[service_name.lower()] = validated_onvif_url(
                        address,
                        allowed_hosts=allowed_hosts,
                    )
                    break
                except OnvifError:
                    continue
    return services


def parse_profiles(data):
    root = parse_xml(data)
    profiles = []
    for profile in descendants(root, "Profiles"):
        token = attr_value(profile, "token")
        if not token:
            continue
        name = child_text(profile, "Name", token)
        ptz_configuration = first_descendant(profile, "PTZConfiguration")
        video_configuration = first_descendant(profile, "VideoEncoderConfiguration")
        audio_configuration = first_descendant(profile, "AudioEncoderConfiguration")
        resolution = first_descendant(video_configuration, "Resolution")
        profile_data = {
            "name": name,
            "token": token,
            "ptz_configuration_token": attr_value(ptz_configuration, "token"),
            "ptz_node_token": child_text(ptz_configuration, "NodeToken"),
            "video": {
                "encoding": child_text(video_configuration, "Encoding"),
                "width": int(child_text(resolution, "Width", "0") or 0),
                "height": int(child_text(resolution, "Height", "0") or 0),
            },
            "audio": {
                "encoding": child_text(audio_configuration, "Encoding"),
            },
            "default_spaces": {
                "continuous_pan_tilt": child_text(
                    ptz_configuration, "DefaultContinuousPanTiltVelocitySpace"
                ),
                "continuous_zoom": child_text(
                    ptz_configuration, "DefaultContinuousZoomVelocitySpace"
                ),
                "relative_pan_tilt": child_text(
                    ptz_configuration, "DefaultRelativePanTiltTranslationSpace"
                ),
                "relative_zoom": child_text(
                    ptz_configuration, "DefaultRelativeZoomTranslationSpace"
                ),
                "absolute_zoom": child_text(
                    ptz_configuration, "DefaultAbsoluteZoomPositionSpace"
                ),
            },
        }
        profiles.append(profile_data)
    return profiles


def parse_stream_uri(data):
    return child_text(parse_xml(data), "Uri")


def parse_presets(data):
    root = parse_xml(data)
    presets = []
    for preset in descendants(root, "Preset"):
        token = attr_value(preset, "token")
        if not token:
            continue
        name = child_text(preset, "Name", f"Preset {token}")
        presets.append({"name": name, "token": token})
    return presets


def _space_supported(root, name):
    element = first_descendant(root, name)
    return element is not None and any(True for _ in element.iter())


def _capability_bool(root, name):
    if root is None:
        return False
    for element in root.iter():
        if local_name(element.tag) == name and bool_value(element.text):
            return True
        for key, value in element.attrib.items():
            if local_name(key) == name and bool_value(value):
                return True
    return False


def parse_ptz_features(capabilities_data, options_data, profile, nodes_data=None):
    features = []
    capabilities_root = parse_xml(capabilities_data) if capabilities_data else None
    options_root = parse_xml(options_data) if options_data else None
    nodes_root = parse_xml(nodes_data) if nodes_data else None
    spaces = profile.get("default_spaces") or {}

    if spaces.get("continuous_pan_tilt") or _space_supported(
        options_root, "ContinuousPanTiltVelocitySpace"
    ):
        features.append("pt")
    if spaces.get("continuous_zoom") or _space_supported(
        options_root, "ContinuousZoomVelocitySpace"
    ):
        features.append("zoom")
    if spaces.get("relative_pan_tilt") or _space_supported(
        options_root, "RelativePanTiltTranslationSpace"
    ):
        features.append("pt-r")
    if spaces.get("relative_zoom") or _space_supported(
        options_root, "RelativeZoomTranslationSpace"
    ):
        features.append("zoom-r")
    if spaces.get("absolute_zoom") or _space_supported(
        options_root, "AbsoluteZoomPositionSpace"
    ):
        features.append("zoom-a")

    fov_spaces = descendants(
        first_descendant(options_root, "RelativePanTiltTranslationSpace"), "URI"
    )
    if any("TranslationSpaceFov" in (item.text or "") for item in fov_spaces):
        features.append("pt-r-fov")

    if _capability_bool(capabilities_root, "MoveStatus"):
        features.append("move-status")
    if _capability_bool(nodes_root, "HomeSupported"):
        features.append("home")
    return features


def select_profile(profiles, requested=""):
    requested = str(requested or "").strip()
    if requested:
        for profile in profiles:
            if profile["token"] == requested or profile["name"] == requested:
                return profile
    for profile in profiles:
        if profile.get("ptz_configuration_token"):
            return profile
    return profiles[0] if profiles else None


def discover(payload, timeout=5):
    credentials = payload_credentials(payload)
    allowed_hosts = allowed_endpoint_hosts(payload)
    attempts = []
    device_url = None
    device_data = None

    for candidate in device_url_candidates(payload):
        try:
            device_data = soap_post(
                candidate,
                get_device_information_body(),
                credentials=credentials,
                timeout=timeout,
                allowed_hosts=allowed_hosts,
            )
            device_url = candidate
            attempts.append({"endpoint": clean_url(candidate), "ok": True})
            break
        except OnvifError as exc:
            attempts.append(
                {"endpoint": clean_url(candidate), "ok": False, "error": str(exc)}
            )

    if not device_url:
        detail = attempts[-1]["error"] if attempts else "No endpoint candidates."
        raise OnvifError(f"Could not connect to an ONVIF device service: {detail}")

    device = parse_device_information(device_data)
    services = {"device": clean_url(device_url)}
    errors = []
    try:
        capability_data = soap_post(
            device_url,
            get_capabilities_body(),
            credentials=credentials,
            timeout=timeout,
            allowed_hosts=allowed_hosts,
        )
        services.update(parse_service_addresses(capability_data, allowed_hosts=allowed_hosts))
    except OnvifError as exc:
        errors.append(f"Capabilities: {exc}")

    parsed_device = urlparse(device_url)
    base = f"{parsed_device.scheme}://{netloc_without_credentials(parsed_device)}"
    media_url = services.get("media") or f"{base}/onvif/media_service"
    ptz_url = services.get("ptz") or f"{base}/onvif/ptz_service"

    profiles = []
    try:
        profiles = parse_profiles(
            soap_post(
                media_url,
                get_profiles_body(),
                credentials=credentials,
                timeout=timeout,
                allowed_hosts=allowed_hosts,
            )
        )
    except OnvifError as exc:
        errors.append(f"Profiles: {exc}")

    for profile in profiles:
        try:
            stream_uri = parse_stream_uri(
                soap_post(
                    media_url,
                    get_stream_uri_body(profile["token"]),
                    credentials=credentials,
                    timeout=timeout,
                    allowed_hosts=allowed_hosts,
                )
            )
            profile["stream_uri"] = inject_credentials(stream_uri, credentials)
            profile["stream_uri_redacted"] = redact_url(profile["stream_uri"])
        except OnvifError as exc:
            profile["stream_error"] = str(exc)

    selected = select_profile(profiles, payload.get("ptz_profile_token"))
    features = []
    presets = []
    if selected and selected.get("ptz_configuration_token"):
        capabilities_data = None
        options_data = None
        nodes_data = None
        try:
            capabilities_data = soap_post(
                ptz_url,
                get_ptz_capabilities_body(),
                credentials=credentials,
                timeout=timeout,
                allowed_hosts=allowed_hosts,
            )
        except OnvifError as exc:
            errors.append(f"PTZ capabilities: {exc}")
        try:
            options_data = soap_post(
                ptz_url,
                get_ptz_options_body(selected["ptz_configuration_token"]),
                credentials=credentials,
                timeout=timeout,
                allowed_hosts=allowed_hosts,
            )
        except OnvifError as exc:
            errors.append(f"PTZ options: {exc}")
        try:
            nodes_data = soap_post(
                ptz_url,
                get_ptz_nodes_body(),
                credentials=credentials,
                timeout=timeout,
                allowed_hosts=allowed_hosts,
            )
        except OnvifError as exc:
            errors.append(f"PTZ nodes: {exc}")
        features = parse_ptz_features(
            capabilities_data,
            options_data,
            selected,
            nodes_data=nodes_data,
        )
        try:
            presets = parse_presets(
                soap_post(
                    ptz_url,
                    get_presets_body(selected["token"]),
                    credentials=credentials,
                    timeout=timeout,
                    allowed_hosts=allowed_hosts,
                )
            )
        except OnvifError as exc:
            errors.append(f"Presets: {exc}")
        if presets and "presets" not in features:
            features.append("presets")

    return {
        "success": True,
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "device": device,
        "services": {
            key: clean_url(value)
            for key, value in {
                **services,
                "media": media_url,
                "ptz": ptz_url,
            }.items()
            if value
        },
        "profiles": profiles,
        "selected_profile": (
            {"name": selected["name"], "token": selected["token"]} if selected else None
        ),
        "features": features,
        "presets": presets,
        "ptz_supported": bool(features),
        "autotrack_candidate": bool(
            "pt-r-fov" in features and "move-status" in features
        ),
        "endpoint_attempts": attempts,
        "errors": errors,
    }


def cacheable_discovery(result):
    cached = {
        key: value
        for key, value in result.items()
        if key not in ("endpoint_attempts",)
    }
    cached["profiles"] = []
    for profile in result.get("profiles", []):
        cached["profiles"].append(
            {
                key: value
                for key, value in profile.items()
                if key not in ("stream_uri",)
            }
        )
    return cached


def redacted_discovery(result):
    redacted = cacheable_discovery(result)
    redacted["endpoint_attempts"] = result.get("endpoint_attempts", [])
    return redacted
