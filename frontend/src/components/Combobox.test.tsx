import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Combobox, type ComboboxOption } from "./Combobox";

const OPTIONS: ComboboxOption[] = [
  { value: "cl-1", label: "Tata Projects, Chennai", meta: "TATA-CH" },
  { value: "cl-2", label: "Kerala State Electricity Board", meta: "KSEB" },
];

function Harness(props: {
  options?: ComboboxOption[];
  loading?: boolean;
  onSelect?: (option: ComboboxOption) => void;
  onCreate?: (label: string) => void;
}) {
  const [query, setQuery] = useState("");
  return (
    <>
      <label htmlFor="client">Client</label>
      <Combobox
        id="client"
        query={query}
        onQueryChange={setQuery}
        options={props.options ?? OPTIONS}
        loading={props.loading ?? false}
        onSelect={props.onSelect ?? (() => undefined)}
        onCreate={props.onCreate}
        createLabel="Add client"
      />
    </>
  );
}

describe("Combobox", () => {
  it("selects with the keyboard alone", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);

    await user.click(screen.getByLabelText("Client"));
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");

    expect(onSelect).toHaveBeenCalledWith(OPTIONS[1]);
  });

  it("points aria-activedescendant at the highlighted row", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const input = screen.getByLabelText("Client");
    await user.click(input);
    await user.keyboard("{ArrowDown}");

    const active = input.getAttribute("aria-activedescendant");
    expect(active).toBeTruthy();
    expect(screen.getByRole("option", { name: /Tata Projects/ }).id).toBe(active);
  });

  it("withholds the create row while a search is still running", async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn();
    const { rerender } = render(<Harness options={[]} loading onCreate={onCreate} />);

    await user.type(screen.getByLabelText("Client"), "Tata");

    // Mid-search there is nothing to click, so nobody can create a duplicate by accident.
    expect(screen.queryByRole("option", { name: /Add client/ })).not.toBeInTheDocument();
    expect(screen.getByText("Searching…")).toBeInTheDocument();

    rerender(<Harness options={[]} loading={false} onCreate={onCreate} />);
    await user.type(screen.getByLabelText("Client"), "Tata");

    expect(screen.getByRole("option", { name: /Add client/ })).toBeInTheDocument();
  });

  it("closes on Escape without choosing anything", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Harness onSelect={onSelect} />);

    await user.click(screen.getByLabelText("Client"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    await user.keyboard("{ArrowDown}{Escape}");

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
  });
});
