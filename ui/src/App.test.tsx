import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";
import { renderWithClient } from "./test/render";

describe("App", () => {
  it("renders the app title", () => {
    renderWithClient(<App />);

    expect(screen.getByRole("heading", { name: "Quack" })).toBeInTheDocument();
  });
});
