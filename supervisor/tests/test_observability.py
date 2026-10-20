import asyncio
import json
from uuid import uuid4

from correlation import bind, setup_logging
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from observability import CorrelationLogHandler, callbacks

CORR = "corr-aaaa-1111"
CONV = "conv-aaaa-1111"


def _events(capsys):
    return [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]


def test_llm_events_mask_cpf_skip_system_and_carry_ids(capsys, monkeypatch):
    monkeypatch.setenv("LOG_PAYLOAD", "truncated")
    setup_logging("testsvc")
    handler = CorrelationLogHandler()
    run_id = uuid4()

    async def main():
        with bind(CORR, CONV):
            await handler.on_chat_model_start(
                {},
                [
                    [
                        SystemMessage("prompt de sistema que não deve aparecer"),
                        HumanMessage("meu CPF é 123.456.789-09"),
                    ]
                ],
                run_id=run_id,
                metadata={"ls_model_name": "claude-haiku-5-5"},
                invocation_params={"model": "claude-haiku-5-5"},
            )
            resultado = LLMResult(
                generations=[[ChatGeneration(message=AIMessage(content="ok"))]]
            )
            await handler.on_llm_end(resultado, run_id=run_id)

    asyncio.run(main())
    events = _events(capsys)
    dump = json.dumps(events)

    assert "prompt de sistema" not in dump
    assert "123.456.789-09" not in dump

    req = next(e for e in events if e["msg"] == "llm.request")
    assert req["model"] == "claude-haiku-5-5"
    assert req["correlation_id"] == CORR
    assert req["conversation_id"] == CONV

    resp = next(e for e in events if e["msg"] == "llm.response")
    assert resp["payload"] == "ok"
    assert resp["duration_ms"] >= 0


def test_tool_events_carry_name_and_masked_args(capsys, monkeypatch):
    monkeypatch.setenv("LOG_PAYLOAD", "truncated")
    setup_logging("testsvc")
    handler = CorrelationLogHandler()
    run_id = uuid4()

    async def main():
        with bind(CORR, CONV):
            await handler.on_tool_start(
                {"name": "consultar_conta"},
                '{"cpf": "123.456.789-09"}',
                run_id=run_id,
            )
            await handler.on_tool_end("conta encontrada", run_id=run_id, name="consultar_conta")

    asyncio.run(main())
    events = _events(capsys)
    dump = json.dumps(events)

    assert "123.456.789-09" not in dump
    req = next(e for e in events if e["msg"] == "tool.request")
    assert req["tool"] == "consultar_conta"
    assert req["correlation_id"] == CORR
    resp = next(e for e in events if e["msg"] == "tool.response")
    assert resp["payload"] == "conta encontrada"


def test_ids_fall_back_to_langgraph_metadata_without_context(capsys, monkeypatch):
    monkeypatch.setenv("LOG_PAYLOAD", "off")
    setup_logging("testsvc")
    handler = CorrelationLogHandler()

    async def main():
        await handler.on_tool_start(
            {"name": "t"},
            "{}",
            run_id=uuid4(),
            metadata={"correlation_id": "meta-corr-0001", "conversation_id": "meta-conv-0001"},
        )

    asyncio.run(main())
    req = next(e for e in _events(capsys) if e["msg"] == "tool.request")
    assert req["correlation_id"] == "meta-corr-0001"
    assert req["conversation_id"] == "meta-conv-0001"
    assert "payload" not in req  # LOG_PAYLOAD=off omite o conteúdo


def test_callbacks_always_include_log_handler():
    handlers = callbacks()
    assert any(isinstance(h, CorrelationLogHandler) for h in handlers)
