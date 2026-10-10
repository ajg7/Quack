import Markdown from "react-markdown";
import type { ChatMessage } from "../store/chat";
import QuackSprite from "./QuackSprite";
import StepList from "./StepList";

const BUDGET_LABEL: Record<string, string> = {
  steps: "tool-call",
  requests: "Notion request",
  time: "time",
};

function Notice({ tone, children }: { tone: "danger" | "muted"; children: string }) {
  return (
    <p
      role={tone === "danger" ? "alert" : undefined}
      className={`mt-3 text-sm ${tone === "danger" ? "text-danger" : "text-muted"}`}
    >
      {children}
    </p>
  );
}

function AssistantBubble({ message }: { message: ChatMessage }) {
  const waiting = message.status === "streaming" && message.content === "";
  const label = message.steps.some((step) => step.status === "running") ? "Working…" : "Thinking…";

  return (
    <article
      aria-label="Quack"
      className="max-w-[90%] rounded-panel border border-line bg-surface px-4 py-3 text-ink"
    >
      <StepList steps={message.steps} />
      {waiting && (
        <p className="flex items-center gap-2 text-sm text-muted">
          <QuackSprite />
          {label}
        </p>
      )}
      {message.content && (
        <div className="space-y-2 leading-relaxed [&_a]:underline [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5">
          <Markdown>{message.content}</Markdown>
        </div>
      )}
      {message.status === "stopped" && <Notice tone="muted">Stopped before finishing.</Notice>}
      {(message.status === "interrupted" || message.status === "error") && message.error && (
        <Notice tone="danger">{message.error}</Notice>
      )}
      {message.stats?.budget_exhausted && (
        <Notice tone="muted">
          {`Quack reached its ${BUDGET_LABEL[message.stats.budget_exhausted] ?? "budget"} limit, so this answer may be incomplete.`}
        </Notice>
      )}
      {message.status === "interrupted" && message.content && (
        <Notice tone="muted">The text above is incomplete.</Notice>
      )}
      {message.stats && (
        <p className="mt-3 font-mono text-xs text-muted">
          {message.stats.tool_calls} tool calls · {message.stats.input_tokens} in /{" "}
          {message.stats.output_tokens} out · {(message.stats.latency_ms / 1000).toFixed(1)}s
        </p>
      )}
    </article>
  );
}

export default function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <article
          aria-label="You"
          className="max-w-[85%] rounded-panel bg-bubble px-4 py-3 whitespace-pre-wrap text-bubble-ink"
        >
          {message.content}
        </article>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <AssistantBubble message={message} />
    </div>
  );
}
