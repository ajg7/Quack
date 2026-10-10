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
