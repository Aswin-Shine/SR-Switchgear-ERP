import { apiError, jsonResponse, mockFetch } from "@/test/utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, csrfToken, loginUrlFor, request } from "./client";

function setCsrfMeta(content: string) {
  document.head.innerHTML = `<meta name="csrf-token" content="${content}">`;
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.head.innerHTML = "";
});

describe("csrfToken", () => {
  it("reads the meta tag Django renders, because the cookie is HttpOnly", () => {
    setCsrfMeta("abc123");
    expect(csrfToken()).toBe("abc123");
  });

  it("treats an unrendered template tag as no token", () => {
    // What `vite dev` serves: index.html with the tag still literal.
    setCsrfMeta("{{ csrf_token }}");
    expect(csrfToken()).toBeNull();
  });
});

describe("request", () => {
  it("sends the CSRF header on unsafe methods only", async () => {
    setCsrfMeta("tok-1");
    const { fetchMock } = mockFetch({
      "GET /api/v1/job-cards": { results: [] },
      "POST /api/v1/job-cards": { id: "jc-1" },
    });

    await api.get("/job-cards");
    await api.post("/job-cards", { title: "x" });

    const [, getInit] = fetchMock.mock.calls[0] ?? [];
    const [, postInit] = fetchMock.mock.calls[1] ?? [];
    expect((getInit?.headers as Record<string, string>)["X-CSRFToken"]).toBeUndefined();
    expect((postInit?.headers as Record<string, string>)["X-CSRFToken"]).toBe("tok-1");
  });

  it("drops empty query values instead of sending ?owner=", async () => {
    const { calls } = mockFetch({ "GET /api/v1/board": { stages: [], lines_by_stage: {} } });

    await api.get("/board", { owner: "me", client: "", category: undefined, page: 2 });

    expect(calls[0]?.url.search).toBe("?owner=me&page=2");
  });

  it("maps a 409 to a stale transition rather than a generic failure", async () => {
    mockFetch({
      "POST /api/v1/job-lines/l-1/transitions": apiError(409, "stale", "It moved."),
    });

    const error = await request("/job-lines/l-1/transitions", { method: "POST" }).catch(
      (caught: unknown) => caught,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).isStale).toBe(true);
    expect((error as ApiError).isRuleViolation).toBe(false);
  });

  it("keeps field errors attached so a form can show them per field", async () => {
    mockFetch({
      "POST /api/v1/clients": jsonResponse(
        {
          error: {
            code: "validation_error",
            message: "Check the form.",
            fields: { name: ["This field is required."], gstin: ["Invalid GSTIN."] },
          },
        },
        400,
      ),
    });

    const error = (await api.post("/clients", {}).catch((caught: unknown) => caught)) as ApiError;

    expect(error.fields.name).toEqual(["This field is required."]);
    expect(error.fieldMessages()).toContainEqual(["gstin", "Invalid GSTIN."]);
  });

  it("survives an error body that is not JSON at all", async () => {
    mockFetch({
      "GET /api/v1/board": new Response("<html>502</html>", {
        status: 502,
        headers: { "content-type": "text/html" },
      }),
    });

    const error = (await api.get("/board").catch((caught: unknown) => caught)) as ApiError;

    expect(error.status).toBe(502);
    expect(error.message).toContain("502");
  });
});

describe("loginUrlFor", () => {
  it("round-trips the user back to where they were", () => {
    expect(loginUrlFor("/app/board", "?owner=me")).toBe("/login/?next=%2Fapp%2Fboard%3Fowner%3Dme");
  });
});
