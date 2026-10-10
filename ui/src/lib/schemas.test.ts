import { describe, expect, it } from "vitest";
import { parseStreamEvent, sourcesSchema } from "./schemas";

describe("parseStreamEvent", () => {
  it("ignores pings", () => {
    expect(parseStreamEvent("ping", "{}")).toBeNull();
  });

  it("ignores unknown event names", () => {
    expect(parseStreamEvent("mystery", "{}")).toBeNull();
  });

  it("parses a token", () => {
    expect(parseStreamEvent("token", '{"text":"Hi"}')).toEqual({
      type: "token",
      data: { text: "Hi" },
    });
  });

  it("parses progress with args", () => {
    const event = parseStreamEvent(
      "progress",
      JSON.stringify({
        status: "start",
        step: 1,
        tool: "search_notion",
        message: "Searching",
        args: { query: "x" },
      }),
    );
    expect(event?.type).toBe("progress");
  });

  it("keeps the route on a finished step", () => {
    const event = parseStreamEvent(
      "progress",
      JSON.stringify({
        status: "done",
        step: 1,
        tool: "semantic_search",
        message: "finished",
        route: "rag",
      }),
    );
    expect(event).toMatchObject({ type: "progress", data: { route: "rag" } });
  });

  it("accepts a done event with and without a budget flag", () => {
    const base = {
      answer: "a",
      request_id: "r",
      turns: 1,
      tool_calls: 0,
      input_tokens: 1,
      output_tokens: 1,
      latency_ms: 1,
    };
    expect(parseStreamEvent("done", JSON.stringify(base))?.type).toBe("done");
    expect(
      parseStreamEvent("done", JSON.stringify({ ...base, budget_exhausted: "steps" })),
    ).toMatchObject({ data: { budget_exhausted: "steps" } });
    expect(
      parseStreamEvent("done", JSON.stringify({ ...base, budget_exhausted: null }))?.type,
    ).toBe("done");
  });

  it("rejects a malformed payload", () => {
    expect(() => parseStreamEvent("progress", '{"status":"bogus"}')).toThrow();
  });

  it("rejects invalid json", () => {
    expect(() => parseStreamEvent("token", "{nope")).toThrow();
  });
});

describe("sourcesSchema", () => {
  it("accepts a sources response", () => {
    const parsed = sourcesSchema.parse({
      sources: [{ id: "abc", name: "Agoge" }],
      partial: false,
    });
    expect(parsed.sources[0].name).toBe("Agoge");
  });
});
