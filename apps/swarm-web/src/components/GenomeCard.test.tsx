import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { MemoryRouter } from "react-router";
import { createClient } from "../api/client.ts";
import { ApiContext } from "../api/context.tsx";
import type { Agent } from "../api/types.ts";
import { GenomeCard } from "./GenomeCard.tsx";

afterEach(cleanup);

test("shows effective research methods separately from human source provenance", () => {
  const genome: Agent = {
    id: "bio-reader", island_id: "bio", active: true,
    prompt: "Read for biological mechanisms.", allowed_tools: ["paper_text"],
    research_methods: {
      version: 1, domain: "bio", specialist: true,
      instructions: "Inspect experimental units and controlled perturbations.",
      sources: [{ title: "Preclinical reporting guidance", url: "https://grants.nih.gov/" }],
    },
  };
  render(<MemoryRouter><ApiContext.Provider value={createClient({})}><GenomeCard genome={genome} /></ApiContext.Provider></MemoryRouter>);
  const methods = screen.getByText("Research methods");
  fireEvent.click(methods);
  expect(methods.closest("details")?.open).toBe(true);
  expect(screen.getByText("Inspect experimental units and controlled perturbations.")).toBeTruthy();
  fireEvent.click(screen.getByText("Method sources · version 1"));
  expect(screen.getByRole("link", { name: "Preclinical reporting guidance" }).getAttribute("href")).toBe("https://grants.nih.gov/");
});
