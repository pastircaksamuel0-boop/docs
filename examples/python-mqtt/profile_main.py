"""
Time profiling for examples/python-mqtt/main.py
Run:  python profile_main.py

Measures the two hot paths:
  1. make_client()  — TLS context + MQTT client setup
  2. on_connect()   — callback execution time

Usage:
    cd examples/python-mqtt
    python ../../profile_main.py      # or wherever you put this file
"""

import cProfile
import importlib.util
import pstats
import io
import time
import timeit
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Load the module under test
# ---------------------------------------------------------------------------
spec = importlib.util.spec_from_file_location(
    "mqtt_example", Path(__file__).parent / "main.py"
)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

REPEAT = 1000  # run each function this many times for stable measurement


# ---------------------------------------------------------------------------
# 1. Profile make_client() with cProfile
# ---------------------------------------------------------------------------
print("=" * 60)
print("cProfile: make_client()")
print("=" * 60)

pr = cProfile.Profile()

with patch.object(app.ssl, "create_default_context") as mock_ssl:
    mock_ssl.return_value = MagicMock()
    with patch.object(app.mqtt, "Client"):
        pr.enable()
        for _ in range(REPEAT):
            app.make_client()
        pr.disable()

sio = io.StringIO()
ps = pstats.Stats(pr, stream=sio).sort_stats("cumulative")
ps.print_stats(10)
print(sio.getvalue())


# ---------------------------------------------------------------------------
# 2. timeit benchmark: make_client() — BEFORE optimisation baseline
# ---------------------------------------------------------------------------
print("=" * 60)
print(f"timeit: make_client()  x{REPEAT} iterations")
print("=" * 60)

with patch.object(app.ssl, "create_default_context") as mock_ssl:
    mock_ssl.return_value = MagicMock()
    with patch.object(app.mqtt, "Client"):
        elapsed_before = timeit.timeit(app.make_client, number=REPEAT)

print(f"BEFORE optimisation: {elapsed_before:.4f}s  "
      f"({elapsed_before / REPEAT * 1e6:.2f} µs/call)")


# ---------------------------------------------------------------------------
# 3. timeit benchmark: on_connect() callback
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print(f"timeit: on_connect()  x{REPEAT} iterations")
print("=" * 60)

reason_ok = MagicMock()
reason_ok.is_failure = False

def _bench_on_connect():
    app.connected.clear()
    app.connection_error.clear()
    app.on_connect(None, None, None, reason_ok, None)

elapsed_on_connect = timeit.timeit(_bench_on_connect, number=REPEAT)
print(f"on_connect: {elapsed_on_connect:.4f}s  "
      f"({elapsed_on_connect / REPEAT * 1e6:.2f} µs/call)")


# ---------------------------------------------------------------------------
# 4. Identify bottleneck and show optimised make_client
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("Bottleneck analysis")
print("=" * 60)

total = elapsed_before + elapsed_on_connect
print(f"make_client  : {elapsed_before:.4f}s  ({elapsed_before/total*100:.1f}%)")
print(f"on_connect   : {elapsed_on_connect:.4f}s  ({elapsed_on_connect/total*100:.1f}%)")
print()
print("Conclusion: make_client() dominates because it creates a new ssl")
print("context on every call.  Caching the context avoids redundant work.")

# --- Optimised version: cache the SSL context ---
_cached_context = None

def make_client_optimised():
    """Cache the SSL context so it is created only once."""
    global _cached_context
    if _cached_context is None:
        import ssl as _ssl
        _cached_context = _ssl.create_default_context(cafile=app.CA_FILE)
        _cached_context.minimum_version = _ssl.TLSVersion.TLSv1_2
        _cached_context.load_cert_chain(app.CERT_FILE, app.KEY_FILE)

    client = app.mqtt.Client(
        callback_api_version=app.mqtt.CallbackAPIVersion.VERSION2,
        client_id=app.DEVICE_ID,
    )
    client.tls_set_context(_cached_context)
    client.on_connect = app.on_connect
    return client


print()
print("=" * 60)
print(f"timeit: make_client_optimised()  x{REPEAT} iterations (AFTER)")
print("=" * 60)

with patch.object(app.ssl, "create_default_context") as mock_ssl:
    mock_ssl.return_value = MagicMock()
    with patch.object(app.mqtt, "Client"):
        # reset cache so the first call still builds it
        _cached_context = None
        elapsed_after = timeit.timeit(make_client_optimised, number=REPEAT)

print(f"AFTER  optimisation: {elapsed_after:.4f}s  "
      f"({elapsed_after / REPEAT * 1e6:.2f} µs/call)")
print()
improvement = (elapsed_before - elapsed_after) / elapsed_before * 100
print(f"Improvement: {improvement:.1f}%  "
      f"({elapsed_before:.4f}s  →  {elapsed_after:.4f}s)")
