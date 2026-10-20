import logging
import time

import requests
import streamlit as st

from correlation import (
    HEADER_CONVERSATION,
    HEADER_CORRELATION,
    bind,
    log_event,
    new_id,
    safe_payload,
    setup_logging,
)

API_URL = "http://supervisor:8000/chat"

setup_logging("frontend")
logger = logging.getLogger(__name__)

st.set_page_config(page_title="MDBank Assistente", page_icon="🏦")

st.title("MDBank Assistente")

# conversation_id é único por sessão do navegador; cada mensagem ganha um correlation_id próprio.
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = new_id()
if "messages" not in st.session_state:
    st.session_state.messages = []


def chamar_supervisor(payload: dict, headers: dict) -> str:
    started = time.perf_counter()
    log_event(
        logger,
        "frontend",
        "client",
        "request",
        url=API_URL,
        payload=safe_payload(payload["message"]),
    )

    try:
        response = requests.post(API_URL, json=payload, headers=headers)
    except requests.RequestException as e:
        log_event(
            logger,
            "frontend",
            "client",
            "error",
            error=f"{type(e).__name__}: {e}",
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return "Erro ao chamar API"

    echoed = response.headers.get(HEADER_CORRELATION)
    if echoed != headers[HEADER_CORRELATION]:
        logger.warning(
            "correlation_id devolvido pelo supervisor difere do enviado",
            extra={
                "event_fields": {
                    "integration": "frontend",
                    "role": "client",
                    "phase": "mismatch",
                    "sent": headers[HEADER_CORRELATION],
                    "received": echoed,
                }
            },
        )

    if response.status_code == 200:
        data = response.json()
        resposta = data.get("resposta", "Erro na resposta do servidor")
    else:
        resposta = "Erro ao chamar API"

    log_event(
        logger,
        "frontend",
        "client",
        "response",
        status=response.status_code,
        payload=safe_payload(resposta),
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return resposta


for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_input = st.chat_input("Digite sua pergunta")

if user_input:
    correlation_id = new_id()
    conversation_id = st.session_state.conversation_id

    st.session_state.messages.append({"role": "user", "content": user_input})

    with st.chat_message("user"):
        st.markdown(user_input)

    payload = {
        "message": user_input,
        "session_id": conversation_id,
        "client_id": "123",
    }
    headers = {
        HEADER_CORRELATION: correlation_id,
        HEADER_CONVERSATION: conversation_id,
    }

    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            with bind(correlation_id, conversation_id):
                resposta = chamar_supervisor(payload, headers)

        st.markdown(resposta)

    st.session_state.messages.append({"role": "assistant", "content": resposta})
