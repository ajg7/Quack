import { afterEach, describe, expect, it, vi } from "vitest";
import type { StreamEvent } from "./schemas";
import { StreamHttpError, StreamInterruptedError, streamChat } from "./stream";

function sseResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, {
    status,
    headers: { "Content-Type": "text/event-stream" },
  });
}

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

const DONE = {
  answer: "Ten rituals.",
  request_id: "r1",
  turns: 2,
  tool_calls: 1,
  input_tokens: 10,
  output_tokens: 5,
  latency_ms: 1200,
};

async function run(response: Response | Error) {
  const events: StreamEvent[] = [];
  vi.spyOn(window, "fetch").mockImplementation(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  const promise = streamChat({
    sessionId: "s",
    message: "hello",
    signal: new AbortController().signal,
    onEvent: (event) => events.push(event),
  });
  return { events, promise };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("streamChat", () => {
  it("delivers events and resolves after done", async () => {
    const { events, promise } = await run(
      sseResponse([
        frame("start", { request_id: "r1" }),
        frame("ping", {}),
        frame("token", { text: "Ten " }),
        frame("done", DONE),
      ]),
    );
    await expect(promise).resolves.toBeUndefined();
    expect(events.map((event) => event.type)).toEqual(["start", "token", "done"]);
  });

  it("resolves after an error event", async () => {
    const { events, promise } = await run(
      sseResponse([frame("error", { message: "boom", request_id: "r1" })]),
    );
    await expect(promise).resolves.toBeUndefined();
    expect(events[0].type).toBe("error");
  });

  it("rejects as interrupted when the stream ends without done or error", async () => {
    const { events, promise } = await run(
      sseResponse([frame("start", { request_id: "r1" }), frame("token", { text: "Ten " })]),
    );
    await expect(promise).rejects.toBeInstanceOf(StreamInterruptedError);
    expect(events.map((event) => event.type)).toEqual(["start", "token"]);
  });

  it("rejects with the HTTP status on a non-200 response", async () => {
    const { promise } = await run(new Response("nope", { status: 422 }));
    await expect(promise).rejects.toMatchObject({ status: 422 });
    await expect(promise).rejects.toBeInstanceOf(StreamHttpError);
  });

  it("rejects when the network fails", async () => {
    const { promise } = await run(new TypeError("Failed to fetch"));
    await expect(promise).rejects.toBeInstanceOf(TypeError);
  });

  it("does not retry after a failure", async () => {
    const { promise } = await run(sseResponse([frame("token", { text: "x" })]));
    await expect(promise).rejects.toBeInstanceOf(StreamInterruptedError);
    expect(window.fetch).toHaveBeenCalledTimes(1);
  });
});
