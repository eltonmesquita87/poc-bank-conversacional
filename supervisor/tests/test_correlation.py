import asyncio
import json
import logging

import pytest
from correlation import (
    CorrelationMiddleware,
    JsonFormatter,
    bind,
    get_conversation_id,
    get_correlation_id,
    log_event,
    mask,
    new_id,
    outbound_headers,
    outbound_metadata,
    resolve_ids,
    safe_payload,
    set_ids,
    setup_logging,
    valid_id,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient

CORR = "corr-aaaa-1111"
CONV = "conv-aaaa-1111"


# -----------------------------
# IDs
# -----------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (new_id(), True),
        ("abc.DEF_123-xyz", True),
        ("short", False),  # menos de 8
        ("x" * 65, False),  # mais de 64
        ("has space 1234", False),
        ("ataque\nlog-injection", False),
        (None, False),
        (12345678, False),
    ],
)
def test_valid_id(value, expected):
    assert valid_id(value) is expected


def test_bind_propagates_to_tasks_and_restores():
    async def child():
        await asyncio.sleep(0)
        return get_correlation_id(), get_conversation_id()

    async def main():
        with bind(CORR, CONV):
            t = asyncio.create_task(child())
            gathered = await asyncio.gather(child())
            assert await t == (CORR, CONV)
            assert gathered == [(CORR, CONV)]
        assert get_correlation_id() is None
        assert get_conversation_id() is None

    asyncio.run(main())


def test_outbound_headers_and_metadata_follow_context():
    assert outbound_headers() == {}
    assert outbound_metadata() == {}
    with bind(CORR, CONV):
        assert outbound_headers() == {
            "X-Correlation-ID": CORR,
            "X-Conversation-ID": CONV,
        }
        assert outbound_metadata() == {
            "correlation_id": CORR,
            "conversation_id": CONV,
        }


def test_resolve_ids_prefers_metadata_then_header_then_context():
    meta = {"correlation_id": "meta-corr-0001", "conversation_id": "meta-conv-0001"}
    hdrs = {"x-correlation-id": "hdr-corr-0001", "x-conversation-id": "hdr-conv-0001"}

    assert resolve_ids(meta, hdrs) == ("meta-corr-0001", "meta-conv-0001", "metadata")
    assert resolve_ids(None, hdrs) == ("hdr-corr-0001", "hdr-conv-0001", "header")

    with bind(CORR, CONV):
        assert resolve_ids(None, None) == (CORR, CONV, "contexto")


def test_resolve_ids_generates_when_nothing_valid():
    corr, conv, origem = resolve_ids({"correlation_id": "x"}, {"x-correlation-id": "y"})
    assert valid_id(corr)
    assert conv is None
    assert origem == "novo"


# -----------------------------
# MASCARAMENTO E PAYLOAD
# -----------------------------


def test_mask_cpf_in_nested_structures():
    data = {"a": "CPF 123.456.789-09 aqui", "b": ["12345678909", ("x", 1)]}
    masked = mask(data)
    assert "123.456.789-09" not in json.dumps(masked)
    assert masked["a"] == "CPF ***.***.***-** aqui"
    assert masked["b"][0] == "***.***.***-**"


def test_safe_payload_off_returns_none(monkeypatch):
    monkeypatch.setenv("LOG_PAYLOAD", "off")
    assert safe_payload("qualquer coisa") is None


def test_safe_payload_masks_even_in_full_mode(monkeypatch):
    monkeypatch.setenv("LOG_PAYLOAD", "full")
    out = safe_payload("cpf 123.456.789-09")
    assert out == "cpf ***.***.***-**"


def test_safe_payload_truncates_and_reads_env_at_call_time(monkeypatch):
    monkeypatch.setenv("LOG_PAYLOAD", "truncated")
    monkeypatch.setenv("LOG_PAYLOAD_MAX_CHARS", "10")
    out = safe_payload("0123456789ABCDEF")
    assert out.startswith("0123456789")
    assert out.endswith("(+6 chars)")

    # Mudança de env depois do import deve valer na próxima chamada.
    monkeypatch.setenv("LOG_PAYLOAD_MAX_CHARS", "100")
    assert safe_payload("0123456789ABCDEF") == "0123456789ABCDEF"


def test_safe_payload_serializes_dict(monkeypatch):
    monkeypatch.setenv("LOG_PAYLOAD", "full")
    out = safe_payload({"nome": "João", "n": 1})
    assert json.loads(out) == {"nome": "João", "n": 1}


# -----------------------------
# LOGGING JSON
# -----------------------------


def test_json_formatter_emits_fixed_fields():
    rec = logging.LogRecord("a2a.client", logging.INFO, __file__, 1, "x", None, None)
    rec.service = "supervisor"
    rec.correlation_id = CORR
    rec.conversation_id = CONV
    rec.event_fields = {"integration": "a2a", "role": "client", "phase": "request"}

    data = json.loads(JsonFormatter().format(rec))

    assert data["service"] == "supervisor"
    assert data["logger"] == "a2a.client"
    assert data["correlation_id"] == CORR
    assert data["conversation_id"] == CONV
    assert data["integration"] == "a2a"
    assert data["level"] == "INFO"
    assert "ts" in data


def test_setup_logging_injects_ids_into_child_loggers(capsys, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    setup_logging("testsvc")

    with bind(CORR, CONV):
        # Logger filho, como os `a2a.*` do SDK: precisa receber os IDs mesmo assim.
        log_event(
            logging.getLogger("a2a.client"),
            "a2a",
            "client",
            "request",
            payload=safe_payload("meu CPF 123.456.789-09"),
        )

    line = capsys.readouterr().out.strip().splitlines()[-1]
    data = json.loads(line)

    assert data["service"] == "testsvc"
    assert data["logger"] == "a2a.client"
    assert data["correlation_id"] == CORR
    assert data["conversation_id"] == CONV
    assert data["msg"] == "a2a.request"
    assert data["payload"] == "meu CPF ***.***.***-**"
    assert "123.456.789-09" not in line


def test_log_event_error_phase_uses_error_level(capsys, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    setup_logging("testsvc")
    log_event(logging.getLogger("t"), "mcp", "client", "error", error="boom")
    data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert data["level"] == "ERROR"
    assert data["msg"] == "mcp.error"


# -----------------------------
# MIDDLEWARE HTTP
# -----------------------------


def _build_app(route_handler):
    app = Starlette(routes=[Route("/", route_handler, methods=["GET", "POST"])])
    return CorrelationMiddleware(app)


async def _echo(request: Request):
    return JSONResponse(
        {
            "correlation_id": get_correlation_id(),
            "conversation_id": get_conversation_id(),
        }
    )


def test_middleware_echoes_valid_header_and_binds_context():
    client = TestClient(_build_app(_echo))
    resp = client.get(
        "/",
        headers={"X-Correlation-ID": CORR, "X-Conversation-ID": CONV},
    )
    assert resp.status_code == 200
    assert resp.headers["X-Correlation-ID"] == CORR
    assert resp.json() == {"correlation_id": CORR, "conversation_id": CONV}


def test_middleware_replaces_invalid_header_with_generated_uuid():
    client = TestClient(_build_app(_echo))
    resp = client.get("/", headers={"X-Correlation-ID": "x"})
    generated = resp.headers["X-Correlation-ID"]
    assert generated != "x"
    assert valid_id(generated)
    assert resp.json()["conversation_id"] is None


def test_middleware_generates_id_when_header_missing():
    client = TestClient(_build_app(_echo))
    first = client.get("/").headers["X-Correlation-ID"]
    second = client.get("/").headers["X-Correlation-ID"]
    assert valid_id(first) and valid_id(second)
    assert first != second


def test_endpoint_set_ids_is_reflected_in_response_header():
    # Simula POST / (AG-UI): o endpoint troca o correlation_id pelo run_id.
    async def handler(request: Request):
        set_ids(correlation_id="run-abc-123456", conversation_id="thread-1-abc")
        return JSONResponse({"ok": True})

    client = TestClient(_build_app(handler))
    resp = client.post("/", headers={"X-Correlation-ID": CORR})
    assert resp.headers["X-Correlation-ID"] == "run-abc-123456"


def test_middleware_works_with_streaming_response():
    async def stream_handler(request: Request):
        async def gen():
            yield "data: 1\n\n"
            yield f"data: {get_correlation_id()}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    client = TestClient(_build_app(stream_handler))
    resp = client.post("/", headers={"X-Correlation-ID": CORR})
    assert resp.headers["X-Correlation-ID"] == CORR
    assert f"data: {CORR}" in resp.text


def test_middleware_logs_request_and_response(capsys, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    setup_logging("testsvc")
    client = TestClient(_build_app(_echo))
    client.get("/", headers={"X-Correlation-ID": CORR})

    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    http_events = [e for e in events if e["logger"] == "http"]
    msgs = [e["msg"] for e in http_events]
    assert "http.request" in msgs
    assert "http.response" in msgs
    assert all(e["correlation_id"] == CORR for e in http_events)
    response_event = next(e for e in http_events if e["msg"] == "http.response")
    assert response_event["status"] == 200
    assert response_event["duration_ms"] >= 0


# -----------------------------
# MCP (só roda se `mcp` estiver instalado no venv)
# -----------------------------


def test_mcp_client_factory_injects_headers_on_request():
    pytest.importorskip("mcp")
    import httpx
    from correlation import mcp_http_client_factory

    client = mcp_http_client_factory()
    assert isinstance(client, httpx.AsyncClient)

    hook = client.event_hooks["request"][-1]
    request = httpx.Request("POST", "http://recursos:8000/mcp_gateway")

    with bind(CORR, CONV):
        asyncio.run(hook(request))

    assert request.headers["X-Correlation-ID"] == CORR
    assert request.headers["X-Conversation-ID"] == CONV
