import { expect, test } from "@playwright/test";
import type { Page, Route } from "@playwright/test";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "*",
  "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
};

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

const DONE = {
  answer: "You have **10** rituals today.",
  request_id: "r1",
  turns: 2,
  tool_calls: 1,
  input_tokens: 100,
  output_tokens: 20,
  latency_ms: 2500,
};

async function mockBackend(page: Page, chat: (route: Route) => Promise<void>) {
  await page.route("**/health", (route) =>
    route.fulfill({ json: { status: "ok", model: "claude-test" }, headers: CORS }),
  );
  await page.route("**/models", (route) =>
    route.fulfill({
      json: {
        default: "claude-opus-5-5",
        models: [
          { id: "claude-opus-5-5", label: "Opus 5.5" },
          { id: "claude-sonnet-5-5", label: "Sonnet 5.5" },
        ],
      },
      headers: CORS,
    }),
  );
  await page.route("**/sources", (route) =>
    route.fulfill({
      json: { sources: [{ id: "1", name: "Agoge" }], partial: false },
      headers: CORS,
    }),
  );
  await page.route("**/sessions/*", (route) =>
    route.fulfill({ json: { cleared: true }, headers: CORS }),
  );
  await page.route("**/chat", async (route) => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: CORS });
      return;
    }
    await chat(route);
  });
}

test("the app loads and shows the backend", async ({ page }) => {
  await mockBackend(page, async (route) => route.abort());
  await page.goto("/");

  await expect(page).toHaveTitle("Quack");
  await expect(page.getByRole("heading", { name: "Quack" })).toBeVisible();
  await expect(page.getByRole("status").and(page.getByText("claude-opus-5-5"))).toBeVisible();
  await expect(page.getByText("Agoge", { exact: true })).toBeVisible();
});

test("a question streams progress and a final answer", async ({ page }) => {
  await mockBackend(page, (route) =>
    route.fulfill({
      status: 200,
      headers: { ...CORS, "Content-Type": "text/event-stream" },
      body: [
        frame("start", { request_id: "r1" }),
        frame("progress", {
          status: "start",
          step: 1,
          tool: "query_database",
          message: "Querying a database with a filter",
        }),
        frame("progress", {
          status: "done",
          step: 1,
          tool: "query_database",
          message: "query_database finished",
        }),
        frame("token", { text: "You have " }),
        frame("done", DONE),
      ].join(""),
    }),
  );
  await page.goto("/");

  await page.getByLabel("Message").fill("What are today's Agoge rituals?");
  await page.getByLabel("Message").press("Enter");

  await expect(page.getByText("Step 1: Querying a database with a filter")).toBeVisible();
  await expect(page.getByText("10", { exact: true })).toBeVisible();
  await expect(page.getByText("1 tool calls")).toBeVisible();
  await expect(page.getByLabel("Message")).toHaveValue("");
});

test("a stream that ends without done is reported as lost, not as an answer", async ({ page }) => {
  await mockBackend(page, (route) =>
    route.fulfill({
      status: 200,
      headers: { ...CORS, "Content-Type": "text/event-stream" },
      body: [frame("start", { request_id: "r1" }), frame("token", { text: "You have " })].join(""),
    }),
  );
  await page.goto("/");

  await page.getByLabel("Message").fill("rituals?");
  await page.getByLabel("Message").press("Enter");

  await expect(page.getByRole("alert")).toContainText("lost before the answer finished");
  await expect(page.getByText("The text above is incomplete.")).toBeVisible();
  await expect(page.getByText("1 tool calls")).toHaveCount(0);
});

test("an unreachable backend is reported", async ({ page }) => {
  await mockBackend(page, (route) => route.abort("connectionrefused"));
  await page.goto("/");

  await page.getByLabel("Message").fill("rituals?");
  await page.getByLabel("Message").press("Enter");

  await expect(page.getByRole("alert")).toContainText("Couldn't reach Quack's backend");
});

test("New chat clears the conversation", async ({ page }) => {
  await mockBackend(page, (route) =>
    route.fulfill({
      status: 200,
      headers: { ...CORS, "Content-Type": "text/event-stream" },
      body: [frame("start", { request_id: "r1" }), frame("done", DONE)].join(""),
    }),
  );
  await page.goto("/");

  await page.getByLabel("Message").fill("q");
  await page.getByLabel("Message").press("Enter");
  await expect(page.getByText("10", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "New chat" }).click();

  await expect(page.getByText("Ask about your Notion")).toBeVisible();
});

test("Send is disabled until there is text", async ({ page }) => {
  await mockBackend(page, async (route) => route.abort());
  await page.goto("/");

  await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();
  await page.getByLabel("Message").fill("hi");
  await expect(page.getByRole("button", { name: "Send" })).toBeEnabled();
});

test("Shift+Enter adds a newline instead of sending", async ({ page }) => {
  let sent = false;
  await mockBackend(page, async (route) => {
    sent = true;
    await route.abort();
  });
  await page.goto("/");

  await page.getByLabel("Message").fill("line one");
  await page.getByLabel("Message").press("Shift+Enter");
  await page.getByLabel("Message").pressSequentially("line two");

  await expect(page.getByLabel("Message")).toHaveValue("line one\nline two");
  expect(sent).toBe(false);
});

test("the selected model is sent with the question", async ({ page }) => {
  let body: { model?: string; message?: string } = {};
  await mockBackend(page, async (route) => {
    body = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      headers: { ...CORS, "Content-Type": "text/event-stream" },
      body: [frame("start", { request_id: "r1" }), frame("done", DONE)].join(""),
    });
  });
  await page.goto("/");

  await page.getByLabel("Model").selectOption("claude-sonnet-5-5");
  await page.getByLabel("Message").fill("rituals?");
  await page.getByLabel("Message").press("Enter");

  await expect(page.getByText("10", { exact: true })).toBeVisible();
  expect(body.model).toBe("claude-sonnet-5-5");
  expect(body.message).toBe("rituals?");
});

test("Stop ends a running answer and says so", async ({ page }) => {
  await mockBackend(page, () => new Promise<void>(() => {}));
  await page.goto("/");

  await page.getByLabel("Message").fill("rituals?");
  await page.getByLabel("Message").press("Enter");
  await page.getByRole("button", { name: "Stop" }).click();

  await expect(page.getByText("Stopped before finishing.")).toBeVisible();
  await expect(page.getByLabel("Message")).toBeEnabled();
});

test("a partial sources list is flagged", async ({ page }) => {
  await mockBackend(page, async (route) => route.abort());
  await page.route("**/sources", (route) =>
    route.fulfill({
      json: { sources: [{ id: "1", name: "Agoge" }], partial: true },
      headers: CORS,
    }),
  );
  await page.goto("/");

  await expect(page.getByText("(list may be incomplete)")).toBeVisible();
});

test("a failing sources endpoint shows an alert", async ({ page }) => {
  await mockBackend(page, async (route) => route.abort());
  await page.route("**/sources", (route) =>
    route.fulfill({ status: 500, json: { detail: "boom" }, headers: CORS }),
  );
  await page.goto("/");

  await expect(page.getByRole("alert")).toContainText("Could not load the list of Notion databases");
});
