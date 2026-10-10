import type * as StreamModule from "../lib/stream";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DoneEvent, StreamEvent } from "../lib/schemas";
import { StreamHttpError, StreamInterruptedError } from "../lib/stream";
import { applyProgress, describeFailure, useChatStore } from "./chat";

const streamChat = vi.hoisted(() => vi.fn());
const clearSession = vi.hoisted(() => vi.fn());

vi.mock("../lib/stream", async (importOriginal) => ({
  ...(await importOriginal<typeof StreamModule>()),
  streamChat,
}));
vi.mock("../lib/api", () => ({ clearSession }));

const DONE: DoneEvent = {
  answer: "Ten rituals.",
  request_id: "r1",
  turns: 2,
  tool_calls: 1,
  input_tokens: 10,
  output_tokens: 5,
  latency_ms: 1200,
};

function scripted(events: StreamEvent[], then?: () => Promise<void> | void) {
  streamChat.mockImplementation(async ({ onEvent }: { onEvent: (e: StreamEvent) => void }) => {
    for (const event of events) onEvent(event);
    await then?.();
  });
}

const progress = (status: "start" | "done" | "error", step = 1) =>
  ({
    type: "progress",
    data: { status, step, tool: "search_notion", message: `Searching ${status}` },
  }) as StreamEvent;

beforeEach(async () => {
  streamChat.mockReset();
  clearSession.mockReset();
  clearSession.mockResolvedValue(undefined);
  await useChatStore.getState().reset();
});

describe("applyProgress", () => {
  it("adds a running step on start", () => {
    const steps = applyProgress([], {
      status: "start",
      step: 1,
      tool: "get_page",
      message: "Reading a page",
    });
    expect(steps).toEqual([
      { step: 1, tool: "get_page", message: "Reading a page", status: "running" },
    ]);
  });

  it("completes the matching step and keeps its message", () => {
    const started = applyProgress([], {
      status: "start",
      step: 1,
      tool: "get_page",
      message: "Reading a page",
    });
    const finished = applyProgress(started, {
      status: "done",
      step: 1,
      tool: "get_page",
      message: "get_page finished",
    });
    expect(finished[0]).toMatchObject({ status: "done", message: "Reading a page" });
  });

  it("marks failures", () => {
    const steps = applyProgress([], {
      status: "error",
      step: 2,
      tool: "get_page",
      message: "get_page failed",
    });
    expect(steps[0].status).toBe("error");
  });
});

describe("describeFailure", () => {
  it("is honest about an interrupted stream", () => {
    expect(describeFailure(new StreamInterruptedError())).toMatch(/lost before the answer/);
  });

  it("names the HTTP status", () => {
    expect(describeFailure(new StreamHttpError(500))).toMatch(/HTTP 500/);
  });

  it("falls back to unreachable", () => {
    expect(describeFailure(new TypeError("Failed to fetch"))).toMatch(/Couldn't reach/);
  });
});

describe("send", () => {
  it("streams tokens, steps and the final answer", async () => {
    scripted([
      progress("start"),
      progress("done"),
      { type: "token", data: { text: "Ten " } },
      { type: "done", data: DONE },
    ]);

    await useChatStore.getState().send("What are today's rituals?");

    const { messages, isStreaming } = useChatStore.getState();
    expect(isStreaming).toBe(false);
    expect(messages).toHaveLength(2);
    expect(messages[0]).toMatchObject({ role: "user", content: "What are today's rituals?" });
    expect(messages[1]).toMatchObject({
      role: "assistant",
      content: "Ten rituals.",
      status: "done",
      stats: DONE,
    });
    expect(messages[1].steps[0].status).toBe("done");
  });

  it("ignores blank input and concurrent sends", async () => {
    scripted([{ type: "done", data: DONE }]);
    await useChatStore.getState().send("   ");
    expect(streamChat).not.toHaveBeenCalled();
  });

  it("marks the message interrupted when the stream dies mid-answer", async () => {
    streamChat.mockImplementation(async ({ onEvent }: { onEvent: (e: StreamEvent) => void }) => {
      onEvent({ type: "token", data: { text: "Ten " } });
      throw new StreamInterruptedError();
    });

    await useChatStore.getState().send("q");

    const assistant = useChatStore.getState().messages[1];
    expect(assistant.status).toBe("interrupted");
    expect(assistant.content).toBe("Ten ");
    expect(assistant.error).toMatch(/lost before the answer/);
    expect(useChatStore.getState().isStreaming).toBe(false);
  });

  it("reports an unreachable backend", async () => {
    streamChat.mockRejectedValue(new TypeError("Failed to fetch"));

    await useChatStore.getState().send("q");

    const assistant = useChatStore.getState().messages[1];
    expect(assistant.status).toBe("interrupted");
    expect(assistant.error).toMatch(/Couldn't reach/);
  });

  it("shows the server's error event and does not overwrite it", async () => {
    scripted([{ type: "error", data: { message: "RateLimitError: slow down" } }]);

    await useChatStore.getState().send("q");

    const assistant = useChatStore.getState().messages[1];
    expect(assistant.status).toBe("error");
    expect(assistant.error).toBe("RateLimitError: slow down");
  });

  it("marks the message stopped when the user aborts", async () => {
    streamChat.mockImplementation(
      ({ signal }: { signal: AbortSignal }) =>
        new Promise<void>((resolve) => {
          signal.addEventListener("abort", () => resolve());
        }),
    );

    const pending = useChatStore.getState().send("q");
    expect(useChatStore.getState().isStreaming).toBe(true);
    useChatStore.getState().stop();
    await pending;

    expect(useChatStore.getState().messages[1].status).toBe("stopped");
    expect(useChatStore.getState().isStreaming).toBe(false);
  });
});

describe("reset", () => {
  it("clears messages, rotates the session and tells the backend", async () => {
    scripted([{ type: "done", data: DONE }]);
    await useChatStore.getState().send("q");
    const before = useChatStore.getState().sessionId;

    await useChatStore.getState().reset();

    expect(useChatStore.getState().messages).toEqual([]);
    expect(useChatStore.getState().sessionId).not.toBe(before);
    expect(clearSession).toHaveBeenLastCalledWith(before);
  });

  it("survives a backend that is down", async () => {
    clearSession.mockRejectedValue(new Error("down"));
    await expect(useChatStore.getState().reset()).resolves.toBeUndefined();
  });
});
