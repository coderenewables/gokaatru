import { describe, expect, it, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import { CopilotView } from "../components/CopilotView";
import { SUPPORTED_COPILOT_PROVIDERS } from "../lib/copilotAgent";
import { useWorkspaceStore } from "../store/useWorkspaceStore";

beforeEach(() => {
  // jsdom does not implement Element#scrollTo, which the thread auto-scroll calls.
  Element.prototype.scrollTo = () => {};
  useWorkspaceStore.setState({
    chatSettings: { provider: "openai", model: "gpt-4o", apiKey: "" },
  });
});

describe("CopilotView settings", () => {
  it("offers exactly the supported providers", () => {
    render(<CopilotView />);
    const select = screen.getByLabelText("Provider") as HTMLSelectElement;
    const offered = Array.from(select.options).map((o) => o.value);
    expect(offered).toEqual([...SUPPORTED_COPILOT_PROVIDERS]);
    expect(offered).not.toContain("anthropic");
  });

  it("says plainly that a saved unsupported provider was replaced", () => {
    useWorkspaceStore.setState({
      chatSettings: { provider: "openai", model: "gpt-4o", apiKey: "k", replacedProvider: "anthropic" },
    });
    render(<CopilotView />);
    expect(screen.getByText(/saved provider "anthropic" is not supported yet and was replaced/i)).toBeTruthy();
  });

  it("shows the data-change control unchecked with a one-sentence explanation", () => {
    render(<CopilotView />);
    const box = screen.getByLabelText(/Allow the assistant to change session data/i) as HTMLInputElement;
    expect(box.checked).toBe(false);
    expect(screen.getByText(/can change session data without asking for each change/i)).toBeTruthy();
  });
});
