import { useHealth } from "../hooks/useBackend";
import { useChatStore } from "../store/chat";

export default function Header() {
  const health = useHealth();
  const reset = useChatStore((state) => state.reset);
  const hasMessages = useChatStore((state) => state.messages.length > 0);

  const online = health.isSuccess;

  return (
    <header className="border-b border-header-line bg-header">
      <div className="mx-auto flex max-w-3xl items-center justify-between gap-4 px-4 py-3">
        <h1 className="font-sans text-2xl font-extrabold tracking-tight text-header-ink">Quack</h1>
        <div className="flex items-center gap-3">
          <span
            role="status"
            className={`flex items-center gap-2 rounded-full px-3 py-1 font-mono text-xs ${
              online ? "bg-badge text-badge-ink" : "bg-pill text-danger"
            }`}
          >
            <span
              aria-hidden="true"
              className={`size-2 rounded-full ${online ? "bg-ok" : "bg-danger"}`}
            />
            {health.isPending ? "Connecting" : online ? health.data.model : "Backend offline"}
          </span>
          <button
            type="button"
            onClick={() => void reset()}
            disabled={!hasMessages}
            className="rounded-full border border-ghost-line px-3 py-1 text-sm font-semibold text-ghost-ink disabled:opacity-40"
          >
            New chat
          </button>
        </div>
      </div>
    </header>
  );
}
