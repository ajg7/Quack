import type { Step } from "../store/chat";

const ICON: Record<Step["status"], string> = {
  running: "…",
  done: "✓",
  error: "!",
};

const TONE: Record<Step["status"], string> = {
  running: "text-muted",
  done: "text-ok",
  error: "text-danger",
};

const ROUTE_LABEL: Record<string, string> = {
  rag: "index",
  live_fallback: "live fallback",
};

export default function StepList({ steps }: { steps: Step[] }) {
  if (steps.length === 0) return null;

  return (
    <ol aria-label="Progress" className="mb-3 space-y-1 font-mono text-xs">
      {steps.map((step) => (
        <li key={step.step} className={`flex gap-2 ${TONE[step.status]}`}>
          <span aria-hidden="true" className="w-4 text-center">
            {ICON[step.status]}
          </span>
          <span>
            Step {step.step}: {step.message}
            {step.status === "error" ? " (failed)" : ""}
            {step.route && ROUTE_LABEL[step.route] ? ` [${ROUTE_LABEL[step.route]}]` : ""}
          </span>
        </li>
      ))}
    </ol>
  );
}
