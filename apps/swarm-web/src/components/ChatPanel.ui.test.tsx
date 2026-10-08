import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { MemoryRouter } from "react-router";
import { createClient } from "../api/client.ts";
import { ApiContext } from "../api/context.tsx";
import { fakeServer, signIn } from "../test/server.ts";
import { ChatPanel } from "./ChatPanel.tsx";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

function openChat(answer: unknown) {
  signIn();
  const server = fakeServer({ "POST /api/v1/chat": answer });
  const api = createClient({ origin: "", fetch: server.fetch });
  render(<MemoryRouter><ApiContext.Provider value={api}><ChatPanel /></ApiContext.Provider></MemoryRouter>);
  return server;
}

test("a malformed accepted chat response preserves the question for a manual retry", async () => {
  const server = openChat({ answer: 42, cost_micros: 5000 });
  const question = "What did these papers establish?";
  const input = screen.getByRole("textbox", { name: "Message" });
  fireEvent.change(input, { target: { value: question } });
  fireEvent.click(screen.getByRole("button", { name: "send" }));
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("Could not confirm an answer.");
  expect(alert.textContent).toContain("did not match its contract");
  await waitFor(() => expect(input).toHaveProperty("value", question));
  expect(screen.getByRole("button", { name: "send" })).toHaveProperty("disabled", false);
  expect(screen.queryByText("42")).toBeNull();
  expect(screen.queryByText("$0.005 this answer")).toBeNull();
  expect(screen.queryByText("from stored records")).toBeNull();
  expect(screen.queryByText("answer cost not reported")).toBeNull();
  expect(server.calls).toHaveLength(1);
  expect(server.calls[0]?.body).toEqual({ message: question });
});

test("a valid chat answer displays its cost and clears the question", async () => {
  const server = openChat({ answer: "The results support selective routing.", cost_micros: 5000 });
  const input = screen.getByRole("textbox", { name: "Message" });
  fireEvent.change(input, { target: { value: "What changed?" } });
  fireEvent.click(screen.getByRole("button", { name: "send" }));
  expect(await screen.findByText("The results support selective routing.")).toBeTruthy();
  expect(screen.getByText("$0.005 this answer")).toBeTruthy();
  expect(input).toHaveProperty("value", "");
  expect(screen.queryByRole("alert")).toBeNull();
  expect(server.calls).toHaveLength(1);
});
