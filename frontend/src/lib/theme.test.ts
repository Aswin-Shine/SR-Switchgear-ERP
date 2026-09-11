import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useTheme } from "./theme";

afterEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("useTheme", () => {
  it("defaults to light with no stored preference and no matchMedia support", () => {
    const { result } = renderHook(() => useTheme());

    expect(result.current[0]).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("honours an explicitly stored preference over the OS default", () => {
    localStorage.setItem("sr-erp-theme", "dark");

    const { result } = renderHook(() => useTheme());

    expect(result.current[0]).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("toggle flips the theme, persists it, and updates the DOM attribute", () => {
    const { result } = renderHook(() => useTheme());

    act(() => result.current[1]());

    expect(result.current[0]).toBe("dark");
    expect(localStorage.getItem("sr-erp-theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");

    act(() => result.current[1]());

    expect(result.current[0]).toBe("light");
    expect(localStorage.getItem("sr-erp-theme")).toBe("light");
  });
});
