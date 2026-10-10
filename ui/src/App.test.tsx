import type * as StreamModule from "./lib/stream";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { StreamEvent } from "./lib/schemas";
import { StreamInterruptedError } from "./lib/stream";
import { useChatStore } from "./store/chat";
import { renderWithClient } from "./test/render";

const api = vi.hoisted(() => ({
  fetchHealth: vi.fn(),
  fetchSources: vi.fn(),
  clearSession: vi.fn(),
}));
const streamChat = vi.hoisted(() => vi.fn());

vi.mock("./lib/api", () => api);
vi.mock("./lib/stream", async (importOriginal) => ({
  ...(await importOriginal<typeof StreamModule>()),
  streamChat,
}));

const DONE = {
  answer: "You have **10** rituals today.",
  request_id: "r1",
  turns: 2,
  tool_calls: 1,
  input_tokens: 100,
  output_tokens: 20,
  latency_ms: 2500,
};

beforeEach(async () => {
  api.fetchHealth.mockReset().mockResolvedValue({ status: "ok", model: "claude-test" });
  api.fetchSources
    .mockReset()
    .mockResolvedValue({ sources: [{ id: "1", name: "Agoge" }], partial: false });
  api.clearSession.mockReset().mockResolvedValue(undefined);
  streamChat.mockReset();
  await useChatStore.getState().reset();
});

function script(events: StreamEvent[], failure?: Error) {
  streamChat.mockImplementation(async ({ onEvent }: { onEvent: (e: StreamEvent) => void }) => {
    for (const event of events) onEvent(event);
    if (failure) throw failure;
  });
}

describe("App", () => {
  it("shows the model once the backend is healthy", async () => {
    renderWithClient(<App />);

    expect(screen.getByRole("heading", { name: "Quack" })).toBeInTheDocument();
    expect(await screen.findByText("claude-test")).toBeInTheDocument();
  });

  it("says the backend is offline when health fails", async () => {
    api.fetchHealth.mockRejectedValue(new Error("down"));
    renderWithClient(<App />);

    expect(await screen.findByText("Backend offline")).toBeInTheDocument();
  });

  it("lists the databases Quack can see", async () => {
    renderWithClient(<App />);

    expect(await screen.findByText("Agoge")).toBeInTheDocument();
  });

  it("tells the user when the database list cannot load", async () => {
    api.fetchSources.mockRejectedValue(new Error("502"));
    renderWithClient(<App />);

    expect(await screen.findByText(/Could not load the list/)).toBeInTheDocument();
  });

  it("disables Send until there is text", async () => {
    renderWithClient(<App />);

    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Message"), "hi");
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
  });

  it("sends on Enter, renders steps and markdown, and clears the box", async () => {
    script([
      {
        type: "progress",
        data: { status: "start", step: 1, tool: "query_database", message: "Querying a database" },
      },
      {
        type: "progress",
        data: {
          status: "done",
          step: 1,
          tool: "query_database",
          message: "query_database finished",
        },
      },
      { type: "done", data: DONE },
    ]);
    renderWithClient(<App />);

    await userEvent.type(screen.getByLabelText("Message"), "rituals?{Enter}");

    expect(await screen.findByText("10")).toBeInTheDocument();
    expect(screen.getByText("Step 1: Querying a database")).toBeInTheDocument();
    expect(screen.getByText(/1 tool calls · 100 in/)).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toHaveValue("");
    expect(streamChat).toHaveBeenCalledTimes(1);
  });

  it("keeps Shift+Enter for new lines", async () => {
    renderWithClient(<App />);

    await userEvent.type(screen.getByLabelText("Message"), "a{Shift>}{Enter}{/Shift}b");

    expect(streamChat).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Message")).toHaveValue("a\nb");
  });

  it("sends an example question when clicked", async () => {
    script([{ type: "done", data: DONE }]);
    renderWithClient(<App />);

    await userEvent.click(screen.getByRole("button", { name: "What are today's Agoge rituals?" }));

    await waitFor(() => expect(streamChat).toHaveBeenCalledTimes(1));
    expect(streamChat.mock.calls[0][0].message).toBe("What are today's Agoge rituals?");
  });

  it("tells the truth when the backend dies mid-answer", async () => {
    script([{ type: "token", data: { text: "You have" } }], new StreamInterruptedError());
    renderWithClient(<App />);

    await userEvent.type(screen.getByLabelText("Message"), "rituals?{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent(/lost before the answer finished/);
    expect(screen.getByText("The text above is incomplete.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("shows a stop button while streaming and marks the answer stopped", async () => {
    streamChat.mockImplementation(
      ({ signal }: { signal: AbortSignal }) =>
        new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve())),
    );
    renderWithClient(<App />);

    await userEvent.type(screen.getByLabelText("Message"), "slow{Enter}");
    await userEvent.click(await screen.findByRole("button", { name: "Stop" }));

    expect(await screen.findByText("Stopped before finishing.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("clears the conversation with New chat", async () => {
    script([{ type: "done", data: DONE }]);
    renderWithClient(<App />);

    await userEvent.type(screen.getByLabelText("Message"), "q{Enter}");
    await screen.findByText("10");
    await userEvent.click(screen.getByRole("button", { name: "New chat" }));

    expect(await screen.findByText("Ask about your Notion")).toBeInTheDocument();
    expect(api.clearSession).toHaveBeenCalled();
  });
});
