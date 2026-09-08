import type { StageRef } from "@/api/types";
import { action, jobLine } from "@/test/factories";
import { renderWithProviders } from "@/test/utils";
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LineActions } from "./LineActions";

const enquiry: StageRef = { id: "st-1", code: "ENQUIRY", name: "Enquiry" };

describe("LineActions", () => {
  it("renders an available action as an enabled, plain button", () => {
    const line = jobLine({
      available_actions: [action({ action_code: "quote", available: true, blocked_by: null })],
    });

    renderWithProviders(<LineActions line={line} currentStage={enquiry} />);

    const button = screen.getByRole("button", { name: "Quote" });
    expect(button).toBeEnabled();
    expect(button).not.toHaveAttribute("title");
  });

  it("disables a condition-blocked action and explains why, rather than hiding it — reachable without a mouse", () => {
    const line = jobLine({
      available_actions: [
        action({ action_code: "negotiate", available: false, blocked_by: "condition" }),
      ],
    });

    renderWithProviders(<LineActions line={line} currentStage={enquiry} />);

    // aria-disabled, not native disabled: a native disabled button is dropped from the tab
    // order in every browser, so its explanation would be unreachable by keyboard/AT.
    const button = screen.getByRole("button", { name: "Negotiate" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();

    const reasonId = button.getAttribute("aria-describedby");
    expect(reasonId).toBeTruthy();
    expect(document.getElementById(reasonId as string)).toHaveTextContent("Not available yet");
  });

  it("explains a self-approval block in its own words", () => {
    const line = jobLine({
      available_actions: [
        action({ action_code: "confirm", available: false, blocked_by: "self_approval" }),
      ],
    });

    renderWithProviders(<LineActions line={line} currentStage={enquiry} />);

    // The reason stays out of the button's own accessible name (still just "Confirm") and
    // is exposed only as its description, so a screen reader doesn't read it twice.
    const button = screen.getByRole("button", { name: "Confirm" });
    const reasonId = button.getAttribute("aria-describedby");
    expect(document.getElementById(reasonId as string)).toHaveTextContent("Needs a second person");
  });
});
