"""Langfuse observability via OpenTelemetry.

Sets up an OTLP exporter pointed at the Langfuse OTEL endpoint, then
provides an @observe() decorator and propagate_attributes() context
manager that create OTEL spans with Langfuse-compatible attributes.

The GoogleGenAIInstrumentor auto-traces every generate_content call
inside the same pipeline, so LLM spans nest under pipeline spans.

If Langfuse keys are missing or OTEL setup fails, everything degrades
to silent no-ops — the ad pipeline still works.
"""

from __future__ import annotations

import base64
import os
import sys
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()

_initialized = False
_otel_available = False
_tracer = None  # type: Any

# Langfuse OTEL attribute keys
_ATTR_SESSION_ID = "langfuse.session.id"
_ATTR_USER_ID = "langfuse.user.id"
_ATTR_TAGS = "langfuse.tags"
_ATTR_METADATA = "langfuse.metadata"
_ATTR_TRACE_NAME = "langfuse.trace.name"


# ---------------------------------------------------------------------------
# Try to set up OpenTelemetry; fall back to no-ops on failure
# ---------------------------------------------------------------------------

def _setup_otel() -> bool:
    """Configure OTEL tracer provider with Langfuse's OTLP endpoint."""
    global _otel_available, _tracer

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    base_url = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        print(
            "[observability] Langfuse keys not set — tracing disabled. "
            "Add LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to .env to enable.",
            file=sys.stderr,
        )
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        auth_bytes = f"{public_key}:{secret_key}".encode()
        auth_header = base64.b64encode(auth_bytes).decode()

        endpoint = f"{base_url}/api/public/otel/v1/traces"

        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers={"Authorization": f"Basic {auth_header}"},
        )

        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        _tracer = trace.get_tracer("ad-engine")
        _otel_available = True
        return True

    except Exception as exc:
        print(f"[observability] OTEL setup failed — {exc}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Public API: observe decorator
# ---------------------------------------------------------------------------

def observe(fn: Callable[..., Any] | None = None, *, name: str | None = None, **kw: Any):
    """Decorator that creates an OTEL span for the wrapped function.

    Usage::

        @observe(name="evaluate-ad")
        def evaluate_ad(...): ...

    Falls through as a no-op if OTEL is not available.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if not _otel_available or _tracer is None:
            return func

        span_name = name or func.__name__

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with _tracer.start_as_current_span(span_name):
                return func(*args, **kwargs)

        return wrapper

    if fn is not None:
        return decorator(fn)
    return decorator


# ---------------------------------------------------------------------------
# Public API: propagate_attributes context manager
# ---------------------------------------------------------------------------

@contextmanager
def propagate_attributes(
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    trace_name: str | None = None,
    **kw: Any,
):
    """Set Langfuse-specific attributes on the current OTEL span."""
    if not _otel_available:
        yield
        return

    from opentelemetry import trace as otel_trace
    import json as _json

    span = otel_trace.get_current_span()
    if span and span.is_recording():
        if session_id:
            span.set_attribute(_ATTR_SESSION_ID, session_id)
        if user_id:
            span.set_attribute(_ATTR_USER_ID, user_id)
        if tags:
            span.set_attribute(_ATTR_TAGS, _json.dumps(tags))
        if metadata:
            span.set_attribute(_ATTR_METADATA, _json.dumps(metadata))
        if trace_name:
            span.set_attribute(_ATTR_TRACE_NAME, trace_name)

    yield


# ---------------------------------------------------------------------------
# Public API: get_langfuse (span updater)
# ---------------------------------------------------------------------------

class _SpanUpdater:
    """Thin wrapper for setting attributes on the current OTEL span."""

    def update_current_span(self, *, metadata: dict[str, Any] | None = None, **kw: Any) -> None:
        if not _otel_available:
            return
        from opentelemetry import trace as otel_trace
        import json as _json

        span = otel_trace.get_current_span()
        if span and span.is_recording() and metadata:
            span.set_attribute(_ATTR_METADATA, _json.dumps(metadata))

    def flush(self) -> None:
        if not _otel_available:
            return
        from opentelemetry import trace as otel_trace

        provider = otel_trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush()

    def shutdown(self) -> None:
        if not _otel_available:
            return
        from opentelemetry import trace as otel_trace

        provider = otel_trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()


_updater = _SpanUpdater()


def get_langfuse() -> _SpanUpdater:
    """Return the span updater singleton."""
    return _updater


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def init_observability() -> bool:
    """Set up OTEL tracing and GoogleGenAI auto-instrumentation.

    Safe to call multiple times — only runs setup once.
    """
    global _initialized

    if _initialized:
        return _otel_available

    _initialized = True

    if not _setup_otel():
        return False

    try:
        from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor
        from opentelemetry import trace as otel_trace

        provider = otel_trace.get_tracer_provider()
        GoogleGenAIInstrumentor().instrument(tracer_provider=provider)
        print("[observability] Langfuse tracing initialized (OTEL)")
        return True

    except Exception as exc:
        print(f"[observability] GoogleGenAI instrumentation failed — {exc}", file=sys.stderr)
        return _otel_available
