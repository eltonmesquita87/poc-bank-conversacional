import atexit
import logging
import time
from typing import cast

from ag_ui.core import (
    BaseEvent,
    EventType,
    RunAgentInput,
    RunFinishedEvent,
    RunStartedEvent,
)

from ag_ui.encoder import EventEncoder
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from correlation import (
    HEADER_CONVERSATION,
    HEADER_CORRELATION,
    CorrelationMiddleware,
    get_conversation_id,
    get_correlation_id,
    log_event,
    new_id,
    safe_payload,
    set_ids,
    setup_logging,
    valid_id,
)
from observability import flush
from src.schemas import ChatRequest
from src.services import executar_supervisor, executar_supervisor_stream

setup_logging("supervisor")
logger = logging.getLogger(__name__)

app = FastAPI()
atexit.register(flush)  # envia traces pendentes ao Langfuse ao encerrar

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[HEADER_CORRELATION, HEADER_CONVERSATION],
)
# Adicionado por último = mais externo: loga http.* e ecoa X-Correlation-ID em toda resposta.
app.add_middleware(CorrelationMiddleware)


@app.post("/chat")
async def chat_endpoint(payload: ChatRequest):
    if not payload.message:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Campo 'message' é obrigatório",
                "correlation_id": get_correlation_id(),
            },
        )

    # Conversa: header X-Conversation-ID (já lido pelo middleware) ou session_id do corpo.
    if get_conversation_id() is None:
        set_ids(
            conversation_id=(
                payload.session_id if valid_id(payload.session_id) else new_id()
            )
        )

    started = time.perf_counter()
    log_event(logger, "chat", "server", "request", payload=safe_payload(payload.message))
    try:
        resposta = await executar_supervisor(
            texto_usuario=payload.message, session_id=get_conversation_id()
        )
    except Exception as e:
        logger.exception(
            "chat.error",
            extra={
                "event_fields": {
                    "integration": "chat",
                    "role": "server",
                    "phase": "error",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            },
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "correlation_id": get_correlation_id()},
        )

    log_event(
        logger,
        "chat",
        "server",
        "response",
        payload=safe_payload(resposta),
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return {"resposta": resposta, "correlation_id": get_correlation_id()}


@app.post("/")
async def agent_endpoint(input_data: RunAgentInput, request: Request):
    # AG-UI: run_id é o correlation_id do turno e thread_id identifica a conversa.
    # Definido aqui, e não dentro do generator, para o middleware ler o ID certo ao enviar
    # o header X-Correlation-ID (o StreamingResponse copia o contexto antes de enviar).
    if valid_id(input_data.run_id):
        set_ids(correlation_id=input_data.run_id)
    if get_conversation_id() is None:
        set_ids(
            conversation_id=(
                input_data.thread_id if valid_id(input_data.thread_id) else new_id()
            )
        )

    accept_header = request.headers.get("accept")
    if accept_header is None:
        accept_header = "text/event-stream"

    encoder = EventEncoder(accept=accept_header)

    async def event_generator():
        started = time.perf_counter()
        last = input_data.messages[-1] if input_data.messages else None
        log_event(
            logger,
            "chat",
            "server",
            "request",
            payload=safe_payload(getattr(last, "content", None)),
        )

        yield encoder.encode(
            cast(
                BaseEvent,
                RunStartedEvent(
                    type=EventType.RUN_STARTED,
                    thread_id=input_data.thread_id,
                    run_id=input_data.run_id,
                ),
            )
        )

        # Stream events
        async for event in executar_supervisor_stream(input_data):
            yield encoder.encode(cast(BaseEvent, event))

        # Run finished
        yield encoder.encode(
            cast(
                BaseEvent,
                RunFinishedEvent(
                    type=EventType.RUN_FINISHED,
                    thread_id=input_data.thread_id,
                    run_id=input_data.run_id,
                ),
            )
        )
        log_event(
            logger,
            "chat",
            "server",
            "response",
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    return StreamingResponse(event_generator(), media_type=encoder.get_content_type())
