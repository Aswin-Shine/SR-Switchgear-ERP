import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { GrantEntry } from "@/api/types";
import { describe, expect, it } from "vitest";
import { type Grants, can } from "./can";

/**
 * Case table for `can()`, matching `identity.services.has_permission`'s real semantics —
 * see ../../fixtures/permission_cases.json's own description. FRONTEND_PLAN.md describes
 * this as also being read by a pytest suite for cross-language drift control; no such
 * pytest file currently exists, so today this only pins the frontend side.
 */
const FIXTURE = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../fixtures/permission_cases.json",
);

interface Case {
  name: string;
  user_id: string;
  grants: GrantEntry[];
  resource: string;
  action: string;
  object: { owner_user_id?: string | null } | null;
  expected: boolean;
}

const table = JSON.parse(readFileSync(FIXTURE, "utf8")) as {
  schema_version: number;
  cases: Case[];
};

describe("permission_cases.json", () => {
  it("is the version this implementation was written against", () => {
    expect(table.schema_version).toBe(2);
    expect(table.cases.length).toBeGreaterThan(10);
  });

  it.each(table.cases.map((testCase) => [testCase.name, testCase] as const))(
    "%s",
    (_name, testCase) => {
      const grants: Grants = { user_id: testCase.user_id, entries: testCase.grants };
      expect(can(grants, testCase.resource, testCase.action, testCase.object)).toBe(
        testCase.expected,
      );
    },
  );
});

describe("can", () => {
  const grants: Grants = {
    user_id: "u-1",
    entries: [{ resource: "job_card", action: "edit", level: 0, if_owner: true }],
  };

  it("treats an absent object as a question about the action, not the row", () => {
    expect(can(grants, "job_card", "edit")).toBe(true);
    expect(can(grants, "job_card", "edit", { owner_user_id: "u-2" })).toBe(false);
  });

  it("ignores an empty grant list", () => {
    expect(can({ user_id: "u-1", entries: [] }, "job_card", "view")).toBe(false);
  });
});
