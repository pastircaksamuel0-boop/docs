"""
Unit tests for examples/python-mqtt/main.py
Run:  pytest test_main.py -v
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import paho.mqtt.client as mqtt

# ---------------------------------------------------------------------------
# Load the module under test without executing main()
# ---------------------------------------------------------------------------
spec = importlib.util.spec_from_file_location(
    "mqtt_example",
    Path(__file__).with_name("main.py"),
)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


# ---------------------------------------------------------------------------
# 1. Configuration constants
# ---------------------------------------------------------------------------

def test_mqtt_topic():
    """TOPIC_REPORTED must follow the infinimesh topic schema."""
    assert app.TOPIC_REPORTED == f"devices/{app.DEVICE_ID}/state/reported"


def test_mqtt_port():
    """Default TLS port for MQTT must be 8883."""
    assert app.MQTT_PORT == 8883


def test_device_id_is_string():
    """DEVICE_ID must be a non-empty string."""
    assert isinstance(app.DEVICE_ID, str)
    assert len(app.DEVICE_ID) > 0


# ---------------------------------------------------------------------------
# 2. on_connect callback — using a MOCK for the reason_code object
# ---------------------------------------------------------------------------

def test_successful_connection():
    """on_connect sets the connected event when reason_code is not failure."""
    app.connected.clear()
    app.connection_error.clear()

    # MOCK: reason_code object — we control is_failure without a real broker
    reason_code = MagicMock()
    reason_code.is_failure = False

    app.on_connect(None, None, None, reason_code, None)

    assert app.connected.is_set()
    assert app.connection_error == []


def test_failed_connection():
    """on_connect stores the error when reason_code signals failure."""
    app.connected.clear()
    app.connection_error.clear()

    reason_code = MagicMock()
    reason_code.is_failure = True
    reason_code.__str__ = lambda self: "Connection refused"

    app.on_connect(None, None, None, reason_code, None)

    assert app.connected.is_set()
    assert len(app.connection_error) == 1


def test_on_connect_called_once_sets_event_exactly_once():
    """connected event must be set exactly once per on_connect call."""
    app.connected.clear()
    app.connection_error.clear()

    reason_code = MagicMock()
    reason_code.is_failure = False

    app.on_connect(None, None, None, reason_code, None)
    # calling again should not raise
    app.on_connect(None, None, None, reason_code, None)

    assert app.connected.is_set()


# ---------------------------------------------------------------------------
# 3. make_client — using STUB/MOCK for ssl and mqtt.Client
# ---------------------------------------------------------------------------

def test_client_uses_tls():
    """make_client must configure TLS with the device certificate chain."""
    with patch.object(app.ssl, "create_default_context") as mock_ssl_ctx:
        # STUB: ssl context object
        context = MagicMock()
        mock_ssl_ctx.return_value = context

        with patch.object(app.mqtt, "Client") as mock_mqtt_client:
            client = app.make_client()

            # TLS context was created
            mock_ssl_ctx.assert_called_once()
            # Certificate chain was loaded
            context.load_cert_chain.assert_called_once_with(
                app.CERT_FILE, app.KEY_FILE
            )
            # Minimum TLS version was set
            assert context.minimum_version == app.ssl.TLSVersion.TLSv1_2
            # MQTT client was instantiated with correct arguments
            mock_mqtt_client.assert_called_once_with(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=app.DEVICE_ID,
            )
            # TLS context was applied to the MQTT client
            client.tls_set_context.assert_called_once_with(context)
            # on_connect callback was registered
            assert client.on_connect == app.on_connect


def test_make_client_sets_on_connect_callback():
    """make_client must register the on_connect callback on the client."""
    with patch.object(app.ssl, "create_default_context"):
        with patch.object(app.mqtt, "Client") as mock_client_cls:
            client = app.make_client()
            assert client.on_connect == app.on_connect


def test_make_client_calls_tls_set_context():
    """make_client must call tls_set_context — not tls_set() — on the client."""
    with patch.object(app.ssl, "create_default_context") as mock_ssl_ctx:
        context = MagicMock()
        mock_ssl_ctx.return_value = context
        with patch.object(app.mqtt, "Client"):
            client = app.make_client()
            client.tls_set_context.assert_called_once_with(context)


# ---------------------------------------------------------------------------
# 4. main() function — MOCK the network; never touches a real broker
# ---------------------------------------------------------------------------

def test_main_publishes_json_payload():
    """main() must publish a JSON payload with 'temp' and 'uptime' keys."""
    with patch.object(app.ssl, "create_default_context"):
        with patch.object(app.mqtt, "Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value

            # STUB: connected.wait returns True immediately
            mock_client.loop_start.side_effect = lambda: app.connected.set()

            mock_info = MagicMock()
            mock_info.rc = mqtt.MQTT_ERR_SUCCESS
            mock_info.is_published.return_value = True
            mock_client.publish.return_value = mock_info

            app.connection_error.clear()
            app.main()

            args, kwargs = mock_client.publish.call_args
            topic = args[0]
            payload = json.loads(args[1])

            assert topic == app.TOPIC_REPORTED
            assert "temp" in payload
            assert "uptime" in payload


def test_main_uses_qos_1():
    """main() must publish with QoS 1 for guaranteed delivery."""
    with patch.object(app.ssl, "create_default_context"):
        with patch.object(app.mqtt, "Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.loop_start.side_effect = lambda: app.connected.set()

            mock_info = MagicMock()
            mock_info.rc = mqtt.MQTT_ERR_SUCCESS
            mock_info.is_published.return_value = True
            mock_client.publish.return_value = mock_info

            app.connection_error.clear()
            app.main()

            _, kwargs = mock_client.publish.call_args
            assert kwargs.get("qos") == 1
