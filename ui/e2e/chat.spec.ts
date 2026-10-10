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
  await expect(page.getByText("claude-test")).toBeVisible();
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
