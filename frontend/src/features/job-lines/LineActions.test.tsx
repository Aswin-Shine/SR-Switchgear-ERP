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

  it("disables a condition-blocked action and explains why, rather than hiding it", () => {
    const line = jobLine({
      available_actions: [
        action({ action_code: "negotiate", available: false, blocked_by: "condition" }),
      ],
    });

    renderWithProviders(<LineActions line={line} currentStage={enquiry} />);

    const button = screen.getByRole("button", { name: "Negotiate" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Not available yet");
  });

  it("explains a self-approval block in its own words", () => {
    const line = jobLine({
      available_actions: [
        action({ action_code: "confirm", available: false, blocked_by: "self_approval" }),
      ],
    });

    renderWithProviders(<LineActions line={line} currentStage={enquiry} />);

    expect(screen.getByRole("button", { name: "Confirm" })).toHaveAttribute(
      "title",
      "Needs a second person",
    );
  });
});
