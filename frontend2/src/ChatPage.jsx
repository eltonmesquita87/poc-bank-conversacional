import { useAppState } from "./StateContext";
import AppLayout from "./Layout";
import ChatBox from "./components/ChatBox";
import PromptSuggestions from "./components/PromptSuggestions";

// Uma conversa por carga de página: vira thread_id (AG-UI) e X-Conversation-ID.
const CONVERSATION_ID = crypto.randomUUID();

export default function ChatPage() {
  const { messages, setMessages, loading, setLoading, updateState } =
    useAppState();

  async function sendMessage(message) {
    if (!message.trim()) return;

    const userMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: message,
    };
    setMessages((prev) => [...prev, userMessage]);
    setLoading(true);

    // Um correlation_id por turno: é o run_id do AG-UI e vai no header X-Correlation-ID.
    const correlationId = crypto.randomUUID();

    const payload = {
      thread_id: CONVERSATION_ID,
      run_id: correlationId,
      messages: [
        {
          id: crypto.randomUUID(),
          role: "user",
          content: message,
          user: { id: "user-123" },
        },
      ],
      state: {},
      tools: [],
      context: [],
      forwardedProps: {},
    };

    console.info(
      JSON.stringify({
        event: "frontend.request",
        correlation_id: correlationId,
        conversation_id: CONVERSATION_ID,
      })
    );

    const response = await fetch("http://localhost:8080/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        "X-Correlation-ID": correlationId,
        "X-Conversation-ID": CONVERSATION_ID,
      },
      body: JSON.stringify(payload),
    });

    // Lê o header ecoado pelo supervisor (exposto no CORS) para confirmar a correlação.
    console.info(
      JSON.stringify({
        event: "frontend.response",
        correlation_id: correlationId,
        status: response.status,
        echoed_correlation_id: response.headers.get("X-Correlation-ID"),
      })
    );

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");

    let assistantMessage = "";
    const assistantId = crypto.randomUUID();

    setMessages((prev) => [
      ...prev,
      { id: assistantId, role: "assistant", content: "" },
    ]);

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split("\n");

      for (let line of lines) {
        if (!line.startsWith("data:")) continue;
        const jsonStr = line.replace("data:", "").trim();
        if (!jsonStr) continue;

        try {
          const event = JSON.parse(jsonStr);

          if (event.type === "TEXT_MESSAGE_CONTENT") {
            assistantMessage += event.delta;
            setMessages((prev) => {
              const updated = [...prev];
              const index = updated.findIndex((m) => m.id === assistantId);
              if (index !== -1) updated[index].content = assistantMessage;
              return updated;
            });
          }

          if (event.type === "STATE_UPDATE") {
            updateState(event.state);
          }

          if (event.type === "RUN_FINISHED") {
            setLoading(false);
          }
        } catch (err) {
          console.error(err);
        }
      }
    }

    setLoading(false);
  }

  return (
    <AppLayout>
      {messages.length === 0 ? (
        <PromptSuggestions onSelect={sendMessage} />
      ) : (
        <ChatBox
          messages={messages}
          setMessages={setMessages}
          onSend={sendMessage}
          loading={loading}
        />
      )}
    </AppLayout>
  );
}
