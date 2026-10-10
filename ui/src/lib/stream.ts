import { fetchEventSource } from "@microsoft/fetch-event-source";
import { API_URL } from "../config";
import { parseStreamEvent } from "./schemas";
import type { StreamEvent } from "./schemas";

export class StreamInterruptedError extends Error {
  constructor() {
    super("The stream ended before the backend sent a final answer.");
    this.name = "StreamInterruptedError";
  }
}

export class StreamHttpError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`The backend answered with HTTP ${status}.`);
    this.name = "StreamHttpError";
    this.status = status;
  }
}

interface StreamChatOptions {
  sessionId: string;
  message: string;
  signal: AbortSignal;
  onEvent: (event: StreamEvent) => void;
}

export async function streamChat({
  sessionId,
  message,
  signal,
  onEvent,
}: StreamChatOptions): Promise<void> {
  let terminal = false;

  await fetchEventSource(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ session_id: sessionId, message }),
    signal,
    openWhenHidden: true,
    async onopen(response) {
      if (!response.ok) throw new StreamHttpError(response.status);
      const type = response.headers.get("content-type") ?? "";
      if (!type.startsWith("text/event-stream")) throw new StreamInterruptedError();
    },
    onmessage(raw) {
      const event = parseStreamEvent(raw.event, raw.data);
      if (!event) return;
      if (event.type === "done" || event.type === "error") terminal = true;
      onEvent(event);
    },
    onclose() {
      if (!terminal) throw new StreamInterruptedError();
    },
    onerror(error) {
      throw error;
    },
  });
}
