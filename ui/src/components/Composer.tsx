import { useForm } from "@tanstack/react-form";
import { z } from "zod";
import { useChatStore } from "../store/chat";

const composerSchema = z.object({
  message: z
    .string()
    .trim()
    .min(1, "Type a question first.")
    .max(8000, "Keep it under 8000 characters."),
});

export default function Composer() {
  const send = useChatStore((state) => state.send);
  const stop = useChatStore((state) => state.stop);
  const isStreaming = useChatStore((state) => state.isStreaming);

  const form = useForm({
    defaultValues: { message: "" },
    validators: { onChange: composerSchema },
    onSubmit: async ({ value, formApi }) => {
      formApi.reset();
      await send(value.message);
    },
  });

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void form.handleSubmit();
      }}
      className="sticky bottom-0 border-t border-line bg-page"
    >
      <div className="mx-auto flex max-w-3xl items-end gap-2 px-4 py-3">
        <form.Field name="message">
          {(field) => (
            <div className="flex-1">
              <textarea
                aria-label="Message"
                rows={1}
                value={field.state.value}
                placeholder="Ask Quack about your Notion…"
                disabled={isStreaming}
                onChange={(event) => field.handleChange(event.target.value)}
                onBlur={field.handleBlur}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void form.handleSubmit();
                  }
                }}
                className="max-h-40 min-h-11 w-full resize-none rounded-panel border border-composer-line bg-composer px-4 py-2 text-ink placeholder:text-placeholder disabled:opacity-60"
              />
              {field.state.meta.isTouched && field.state.meta.errors.length > 0 && (
                <p role="alert" className="mt-1 text-sm text-danger">
                  {field.state.meta.errors
                    .map((error) => (typeof error === "string" ? error : error?.message))
                    .filter(Boolean)
                    .join(" ")}
                </p>
              )}
            </div>
          )}
        </form.Field>
        {isStreaming ? (
          <button
            type="button"
            onClick={stop}
            className="h-11 rounded-full border border-ghost-line px-5 font-semibold text-ghost-ink"
          >
            Stop
          </button>
        ) : (
          <form.Subscribe selector={(state) => state.values.message.trim().length > 0}>
            {(hasText) => (
              <button
                type="submit"
                disabled={!hasText}
                className="h-11 rounded-full bg-action px-5 font-semibold text-action-ink disabled:opacity-40"
              >
                Send
              </button>
            )}
          </form.Subscribe>
        )}
      </div>
    </form>
  );
}
