import { z } from "zod";

export const startEventSchema = z.object({ request_id: z.string() });

export const progressEventSchema = z.object({
  status: z.enum(["start", "done", "error"]),
  step: z.number(),
  tool: z.string(),
  message: z.string(),
  args: z.record(z.string(), z.unknown()).optional(),
});

export const tokenEventSchema = z.object({ text: z.string() });

export const doneEventSchema = z.object({
  answer: z.string(),
  request_id: z.string(),
  turns: z.number(),
  tool_calls: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  latency_ms: z.number(),
});

export const errorEventSchema = z.object({
  message: z.string(),
  request_id: z.string().optional(),
});

export const healthSchema = z.object({ status: z.string(), model: z.string() });

export const sourcesSchema = z.object({
  sources: z.array(z.object({ id: z.string().nullable(), name: z.string() })),
  partial: z.boolean(),
});

export type ProgressEvent = z.infer<typeof progressEventSchema>;
export type DoneEvent = z.infer<typeof doneEventSchema>;
export type Health = z.infer<typeof healthSchema>;
export type Sources = z.infer<typeof sourcesSchema>;

export type StreamEvent =
  | { type: "start"; data: z.infer<typeof startEventSchema> }
  | { type: "progress"; data: ProgressEvent }
  | { type: "token"; data: z.infer<typeof tokenEventSchema> }
  | { type: "done"; data: DoneEvent }
  | { type: "error"; data: z.infer<typeof errorEventSchema> };

export function parseStreamEvent(name: string, raw: string): StreamEvent | null {
  if (name === "ping") return null;
  const json: unknown = JSON.parse(raw);
  switch (name) {
    case "start":
      return { type: "start", data: startEventSchema.parse(json) };
    case "progress":
      return { type: "progress", data: progressEventSchema.parse(json) };
    case "token":
      return { type: "token", data: tokenEventSchema.parse(json) };
    case "done":
      return { type: "done", data: doneEventSchema.parse(json) };
    case "error":
      return { type: "error", data: errorEventSchema.parse(json) };
    default:
      return null;
  }
}
