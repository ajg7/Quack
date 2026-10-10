import { useEffect, useRef } from "react";
import { useChatStore } from "../store/chat";
import MessageBubble from "./MessageBubble";
import SourcesPanel from "./SourcesPanel";

const NEAR_BOTTOM_PX = 80;

const EXAMPLES = [
  "What are today's Agoge rituals?",
  "Which Odysseys are in progress?",
  "What can you see in my workspace?",
];

function EmptyState() {
  const send = useChatStore((state) => state.send);

  return (
    <section className="space-y-6 py-8">
      <div>
        <h2 className="text-3xl font-extrabold tracking-tight text-ink">Ask about your Notion</h2>
        <p className="mt-1 text-muted">Quack reads your workspace. It never writes to it.</p>
      </div>
      <ul className="flex flex-wrap gap-2">
        {EXAMPLES.map((example) => (
          <li key={example}>
            <button
              type="button"
              onClick={() => void send(example)}
              className="rounded-full border border-ghost-line px-4 py-2 text-sm font-semibold text-ghost-ink"
            >
              {example}
            </button>
          </li>
        ))}
      </ul>
      <SourcesPanel />
    </section>
  );
}

export default function MessageList() {
  const messages = useChatStore((state) => state.messages);
  const bottom = useRef<HTMLDivElement>(null);

  const pinned = useRef(true);

  useEffect(() => {
    const onScroll = () => {
      const distance = document.documentElement.scrollHeight - window.innerHeight - window.scrollY;
      pinned.current = distance < NEAR_BOTTOM_PX;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (pinned.current) bottom.current?.scrollIntoView?.({ block: "end" });
  }, [messages]);

  return (
    <div className="mx-auto w-full max-w-3xl flex-1 px-4">
      {messages.length === 0 ? (
        <EmptyState />
      ) : (
        <div role="log" aria-live="polite" className="space-y-4 py-6">
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
        </div>
      )}
      <div ref={bottom} />
    </div>
  );
}
