import { create } from "zustand";
import { API_URL } from "../config";
import { clearSession } from "../lib/api";
import type { DoneEvent, ProgressEvent, StreamEvent } from "../lib/schemas";
import {
  StreamHttpError,
  StreamInterruptedError,
  StreamProtocolError,
  streamChat,
} from "../lib/stream";

export type MessageStatus = "streaming" | "done" | "error" | "interrupted" | "stopped";
export type StepStatus = "running" | "done" | "error";

export interface Step {
  step: number;
  tool: string;
  message: string;
  status: StepStatus;
  route?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: MessageStatus;
  steps: Step[];
  error?: string;
  stats?: DoneEvent;
}

interface ChatState {
  sessionId: string;
  messages: ChatMessage[];
  isStreaming: boolean;
  model: string | null;
  setModel: (model: string) => void;
  send: (text: string) => Promise<void>;
  stop: () => void;
  reset: () => Promise<void>;
}

let controller: AbortController | null = null;

function newId(): string {
  return crypto.randomUUID();
}

export function describeFailure(error: unknown): string {
  if (error instanceof StreamInterruptedError) {
    return "The connection to Quack's backend was lost before the answer finished. This question was not saved to the conversation, so ask it again.";
  }
  if (error instanceof StreamProtocolError) {
    return "Quack's backend sent something this page could not read. Try the question again.";
  }
  if (error instanceof StreamHttpError && error.status === 409) {
    return "Quack is still answering your previous question. Wait for it to finish, then ask again.";
  }
  if (error instanceof StreamHttpError) {
    return `Quack's backend rejected the request (HTTP ${error.status}).`;
  }
  return `Couldn't reach Quack's backend at ${API_URL}. Check that it is running, then try again.`;
}

export function applyProgress(steps: Step[], event: ProgressEvent): Step[] {
  const status: StepStatus = event.status === "start" ? "running" : event.status;
  const index = steps.findIndex((step) => step.step === event.step);
  if (index === -1) {
    return [
      ...steps,
      { step: event.step, tool: event.tool, message: event.message, status, route: event.route },
    ];
  }
  const next = [...steps];
  next[index] = {
    ...next[index],
    status,
    message: event.status === "start" ? event.message : next[index].message,
    route: event.route ?? next[index].route,
  };
  return next;
}

export const useChatStore = create<ChatState>((set, get) => {
  function patchAssistant(id: string, patch: (message: ChatMessage) => ChatMessage) {
    set((state) => ({
      messages: state.messages.map((message) => (message.id === id ? patch(message) : message)),
    }));
  }

  function handleEvent(id: string, event: StreamEvent) {
    switch (event.type) {
      case "progress":
        patchAssistant(id, (m) => ({ ...m, steps: applyProgress(m.steps, event.data) }));
        break;
      case "token":
        patchAssistant(id, (m) => ({ ...m, content: m.content + event.data.text }));
        break;
      case "done":
        patchAssistant(id, (m) => ({
          ...m,
          content: event.data.answer,
          status: "done",
          stats: event.data,
        }));
        break;
      case "error":
        patchAssistant(id, (m) => ({ ...m, status: "error", error: event.data.message }));
        break;
      default:
        break;
    }
  }

  return {
    sessionId: newId(),
    messages: [],
    isStreaming: false,
    model: null,
    setModel(model) {
      set({ model });
    },
    async send(text) {
      const trimmed = text.trim();
      if (!trimmed || get().isStreaming) return;

      const assistantId = newId();
      const abort = new AbortController();
      controller = abort;
      set((state) => ({
        isStreaming: true,
        messages: [
          ...state.messages,
          { id: newId(), role: "user", content: trimmed, status: "done", steps: [] },
          { id: assistantId, role: "assistant", content: "", status: "streaming", steps: [] },
        ],
      }));

      try {
        await streamChat({
          sessionId: get().sessionId,
          message: trimmed,
          model: get().model ?? undefined,
          signal: abort.signal,
          onEvent: (event) => handleEvent(assistantId, event),
        });
        if (abort.signal.aborted) {
          patchAssistant(assistantId, (m) =>
            m.status === "streaming" ? { ...m, status: "stopped" } : m,
          );
        }
      } catch (error) {
        patchAssistant(assistantId, (m) =>
          m.status === "streaming"
            ? { ...m, status: "interrupted", error: describeFailure(error) }
            : m,
        );
      } finally {
        if (controller === abort) {
          controller = null;
          set({ isStreaming: false });
        }
      }
    },
    stop() {
      controller?.abort();
    },
    async reset() {
      const previous = get().sessionId;
      controller?.abort();
      controller = null;
      set({ sessionId: newId(), messages: [], isStreaming: false });
      try {
        await clearSession(previous);
      } catch {
        return;
      }
    },
  };
});
