import { cx } from "@/lib/cx";
import { useId, useRef, useState } from "react";

export interface ComboboxOption {
  value: string;
  label: string;
  /** Right-aligned secondary text: a client code, a city. */
  meta?: string;
}

export interface ComboboxProps {
  id: string;
  options: ComboboxOption[];
  /** Text in the box. The parent owns it so it can debounce the `?q=` request. */
  query: string;
  onQueryChange: (query: string) => void;
  onSelect: (option: ComboboxOption) => void;
  placeholder?: string;
  loading?: boolean;
  disabled?: boolean;
  required?: boolean;
  invalid?: boolean;
  describedBy?: string;
  /** Offers "Add <query>" as the last row. Used by the enquiry intake form. */
  onCreate?: (label: string) => void;
  createLabel?: string;
  emptyLabel?: string;
}

const CREATE_INDEX = -2;

export function Combobox({
  id,
  options,
  query,
  onQueryChange,
  onSelect,
  placeholder,
  loading = false,
  disabled = false,
  required = false,
  invalid = false,
  describedBy,
  onCreate,
  createLabel = "Add",
  emptyLabel = "No matches",
}: ComboboxProps) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(-1);
  const blurTimer = useRef<number | undefined>(undefined);

  /*
   * "Add <query>" is withheld while a search is in flight. Offering it next to an empty
   * list invites a click that creates a second "Tata Projects" a second before the real
   * one would have appeared, and a duplicate client is not something the user can undo.
   */
  const canCreate = Boolean(onCreate) && query.trim().length > 0 && !loading;
  const lastIndex = options.length - 1;

  function close() {
    setOpen(false);
    setHighlight(-1);
  }

  function choose(index: number) {
    if (index === CREATE_INDEX) {
      onCreate?.(query.trim());
      close();
      return;
    }
    const option = options[index];
    if (!option) return;
    onSelect(option);
    close();
  }

  function move(delta: number) {
    setOpen(true);
    setHighlight((current) => {
      const order = [...options.map((_, index) => index), ...(canCreate ? [CREATE_INDEX] : [])];
      if (order.length === 0) return -1;
      const position = order.indexOf(current);
      const next = position === -1 ? (delta > 0 ? 0 : order.length - 1) : position + delta;
      const wrapped = (next + order.length) % order.length;
      return order[wrapped] ?? -1;
    });
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        move(1);
        break;
      case "ArrowUp":
        event.preventDefault();
        move(-1);
        break;
      case "Home":
        if (open) {
          event.preventDefault();
          setHighlight(0);
        }
        break;
      case "End":
        if (open) {
          event.preventDefault();
          setHighlight(lastIndex);
        }
        break;
      case "Enter":
        if (open && highlight !== -1) {
          event.preventDefault();
          choose(highlight);
        }
        break;
      case "Escape":
        if (open) {
          event.preventDefault();
          close();
        }
        break;
      default:
        break;
    }
  }

  const activeId =
    highlight >= 0
      ? `${listId}-${highlight}`
      : highlight === CREATE_INDEX
        ? `${listId}-create`
        : undefined;

  return (
    <div className="combobox">
      <input
        id={id}
        className={cx("input")}
        type="text"
        role="combobox"
        autoComplete="off"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={activeId}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        aria-busy={loading || undefined}
        required={required}
        disabled={disabled}
        placeholder={placeholder}
        value={query}
        onChange={(event) => {
          onQueryChange(event.target.value);
          setOpen(true);
          setHighlight(-1);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          // Let a click on an option land before the list disappears.
          blurTimer.current = window.setTimeout(close, 120);
        }}
        onKeyDown={onKeyDown}
      />
      {open ? (
        /*
         * ARIA 1.2 combobox: focus never leaves the input, and aria-activedescendant points
         * at the highlighted option. That is why the options are not focusable and carry no
         * key handlers of their own — every key is handled on the input above. The linter's
         * interactive-element rules assume a different (worse) pattern here.
         */
        // biome-ignore lint/a11y/useSemanticElements: listbox is the correct role for this pattern
        // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: ul is the listbox container the spec calls for
        // biome-ignore lint/a11y/useFocusableInteractive: focus stays on the input, per aria-activedescendant
        <ul className="combobox__list" id={listId} role="listbox" aria-label={placeholder}>
          {options.map((option, index) => (
            // biome-ignore lint/a11y/useFocusableInteractive: options are never focused; the input owns focus
            // biome-ignore lint/a11y/useKeyWithClickEvents: keyboard selection is handled on the input
            <li
              key={option.value}
              id={`${listId}-${index}`}
              // biome-ignore lint/a11y/useSemanticElements: option is the correct role inside a listbox
              // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: li is the option element the ARIA pattern calls for
              role="option"
              aria-selected={highlight === index}
              className="combobox__option"
              onMouseEnter={() => setHighlight(index)}
              onMouseDown={(event) => {
                event.preventDefault(); // keep focus, cancel the blur close
                window.clearTimeout(blurTimer.current);
              }}
              onClick={() => choose(index)}
            >
              <span className="truncate">{option.label}</span>
              {option.meta ? <span className="combobox__option-meta">{option.meta}</span> : null}
            </li>
          ))}

          {canCreate ? (
            // biome-ignore lint/a11y/useFocusableInteractive: options are never focused; the input owns focus
            // biome-ignore lint/a11y/useKeyWithClickEvents: keyboard selection is handled on the input
            <li
              id={`${listId}-create`}
              // biome-ignore lint/a11y/useSemanticElements: option is the correct role inside a listbox
              // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: li is the option element the ARIA pattern calls for
              role="option"
              aria-selected={highlight === CREATE_INDEX}
              className="combobox__option"
              onMouseEnter={() => setHighlight(CREATE_INDEX)}
              onMouseDown={(event) => {
                event.preventDefault();
                window.clearTimeout(blurTimer.current);
              }}
              onClick={() => choose(CREATE_INDEX)}
            >
              <span>
                {createLabel} “{query.trim()}”
              </span>
            </li>
          ) : null}

          {options.length === 0 && !canCreate ? (
            <li className="combobox__empty">{loading ? "Searching…" : emptyLabel}</li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}
