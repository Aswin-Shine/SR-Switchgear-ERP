import { describe, expect, it } from "vitest";
import {
  EMPTY_MARK,
  daysSince,
  formatAge,
  formatAmountInput,
  formatDate,
  formatDateTime,
  formatMoney,
  formatQuantity,
  humanizeCode,
  sanitizeAmountInput,
  stageHueClass,
} from "./format";

describe("formatMoney", () => {
  it("groups in lakhs and crores", () => {
    // The whole reason for en-IN: 12345678.9 is ₹1,23,45,678.90, not ₹12,345,678.90.
    expect(formatMoney("12345678.9")).toBe("₹1,23,45,678.90");
  });

  it("keeps a decimal string exact rather than routing it through a float", () => {
    expect(formatMoney("0.15")).toBe("₹0.15");
    expect(formatMoney("999999999999.99")).toBe("₹9,99,99,99,99,999.99");
  });

  it("renders an absent amount as a dash, not as zero", () => {
    expect(formatMoney(null)).toBe(EMPTY_MARK);
    expect(formatMoney("")).toBe(EMPTY_MARK);
    expect(formatMoney(undefined)).toBe(EMPTY_MARK);
  });
});

describe("formatQuantity", () => {
  it("appends the unit when there is one", () => {
    expect(formatQuantity("12", "nos")).toBe("12 nos");
    expect(formatQuantity("1.5")).toBe("1.5");
    expect(formatQuantity(null, "nos")).toBe(EMPTY_MARK);
  });
});

describe("dates", () => {
  it("renders dd/mm/yyyy", () => {
    expect(formatDate("2026-03-14")).toBe("14/03/2026");
  });

  it("renders timestamps in Asia/Kolkata, not UTC", () => {
    // 20:00 UTC is 01:30 the next day in IST (+05:30).
    expect(formatDateTime("2026-03-14T20:00:00Z")).toBe("15/03/2026, 01:30");
  });

  it("returns the empty mark for missing and unparseable values", () => {
    expect(formatDate(null)).toBe(EMPTY_MARK);
    expect(formatDate("not a date")).toBe(EMPTY_MARK);
  });
});

describe("age", () => {
  const now = new Date("2026-03-14T12:00:00Z");

  it("counts whole days", () => {
    expect(daysSince("2026-03-11T12:00:00Z", now)).toBe(3);
    expect(formatAge("2026-03-11T12:00:00Z", now)).toBe("3d");
  });

  it("says today for anything from today or the future", () => {
    expect(formatAge("2026-03-14T09:00:00Z", now)).toBe("today");
    expect(formatAge("2026-03-20T09:00:00Z", now)).toBe("today");
  });
});

describe("stageHueClass", () => {
  it("is stable for a given stage code", () => {
    expect(stageHueClass("QUO")).toBe(stageHueClass("QUO"));
  });

  it("gives an unknown stage a class without any code change", () => {
    // The point of hashing: a stage an administrator adds tomorrow still gets a colour.
    expect(stageHueClass("BRAND-NEW-STAGE")).toMatch(/^stage-chip--h\d{1,2}$/);
  });

  it("spreads a realistic stage list across several hues", () => {
    const codes = ["ENQ", "QUO", "NEG", "ORD", "PRD", "DSP", "CLS", "LST"];
    const distinct = new Set(codes.map(stageHueClass));
    expect(distinct.size).toBeGreaterThanOrEqual(5);
  });
});

describe("humanizeCode", () => {
  it("is the fallback when the server sent no label", () => {
    expect(humanizeCode("in_progress")).toBe("In progress");
    expect(humanizeCode("partial_allowed")).toBe("Partial allowed");
  });
});

describe("formatAmountInput", () => {
  it("groups in lakhs and crores, same as formatMoney but live", () => {
    expect(formatAmountInput("8000000")).toBe("80,00,000");
    expect(formatAmountInput("125000")).toBe("1,25,000");
    expect(formatAmountInput("999")).toBe("999");
  });

  it("keeps an in-progress decimal untouched, unlike Intl.NumberFormat", () => {
    expect(formatAmountInput("8000000.")).toBe("80,00,000.");
    expect(formatAmountInput("8000000.5")).toBe("80,00,000.5");
  });

  it("passes through an empty or short string", () => {
    expect(formatAmountInput("")).toBe("");
    expect(formatAmountInput("5")).toBe("5");
  });
});

describe("sanitizeAmountInput", () => {
  it("strips grouping commas back out", () => {
    expect(sanitizeAmountInput("80,00,000")).toBe("8000000");
  });

  it("keeps only the first decimal point and caps two decimal places", () => {
    expect(sanitizeAmountInput("12.34.56")).toBe("12.34");
    expect(sanitizeAmountInput("12.345")).toBe("12.34");
  });

  it("drops non-numeric characters (currency symbol, letters)", () => {
    expect(sanitizeAmountInput("₹1,23,456abc")).toBe("123456");
  });
});
