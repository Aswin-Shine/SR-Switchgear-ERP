import type { ActionOption, JobLineSummary, Stage, StageRef } from "@/api/types";

/** Deliberately not the fixture stages: tests should not share the app's vocabulary. */
export function stage(
  overrides: Partial<Stage> & { id: string; code: string; name: string },
): Stage {
  return {
    module_code: "sales_pipeline",
    sequence_no: 10,
    department: null,
    is_initial: false,
    is_terminal: false,
    ...overrides,
  };
}

export function stageRef(source: Stage | StageRef): StageRef {
  return { id: source.id, code: source.code, name: source.name };
}

export function action(overrides: Partial<ActionOption> & { action_code: string }): ActionOption {
  return {
    to_stage: null,
    requires_note: false,
    available: true,
    blocked_by: null,
    ...overrides,
  };
}

export function jobLine(overrides: Partial<JobLineSummary> = {}): JobLineSummary {
  return {
    id: "line-1",
    line_no: 1,
    description: "LT panel 800A",
    product_category: { id: "cat-1", code: "PANEL", name: "LT panel", is_manufactured: true },
    quantity: 2,
    line_status: "active",
    required_by: "2026-05-01",
    stage_entered_at: "2026-04-20T09:00:00Z",
    job_card: {
      id: "card-1",
      job_no: "JOB-2026-JAN-0007",
      client: "Acme Switchgear",
      dispatch_policy: "partial_allowed",
    },
    available_actions: [],
    quotation: null,
    ...overrides,
  };
}
