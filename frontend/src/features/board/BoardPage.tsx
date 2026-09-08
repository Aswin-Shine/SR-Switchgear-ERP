import { useBoard } from "@/api/endpoints/board";
import { useClients } from "@/api/endpoints/clients";
import { useMe, useProductCategories } from "@/api/endpoints/reference";
import type { Board, JobLineSummary, Stage } from "@/api/types";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import { Field } from "@/components/Field";
import { PageHead } from "@/components/PageHead";
import { QueryState } from "@/components/QueryState";
import { Select } from "@/components/Select";
import { cx } from "@/lib/cx";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { useId, useState } from "react";
import { useSearchParams } from "react-router";
import { LineCard } from "./LineCard";
import { strings } from "./strings";

const PHONE = "(max-width: 860px)";
const OWNER_ME = "me";

export function BoardPage() {
  const [params, setParams] = useSearchParams();
  const { data: me } = useMe();
  const owner = params.get("owner") ?? undefined;
  const filters = {
    // The URL keeps "owner=me" for a shareable link; the API wants a real user id.
    owner_user_id: owner === OWNER_ME ? me?.id : undefined,
    client: params.get("client") ?? undefined,
    category: params.get("category") ?? undefined,
    q: params.get("q") ?? undefined,
  };
  const board = useBoard(filters);
  const isPhone = useMediaQuery(PHONE);

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  const filtered = Boolean(owner || filters.client || filters.category || filters.q);

  return (
    <div className="stack">
      <PageHead
        title={strings.title}
        subtitle={strings.subtitle}
        actions={
          filtered ? (
            <Button onClick={() => setParams(new URLSearchParams(), { replace: true })}>
              {strings.clearFilters}
            </Button>
          ) : null
        }
      />

      <BoardFilters
        filters={{ owner, client: filters.client, category: filters.category, q: filters.q }}
        onChange={setFilter}
      />

      <QueryState query={board} skeletonRows={6}>
        {(data) => (isPhone ? <PhoneBoard board={data} /> : <DeskBoard board={data} />)}
      </QueryState>
    </div>
  );
}

function BoardFilters({
  filters,
  onChange,
}: {
  filters: Record<string, string | undefined>;
  onChange: (key: string, value: string) => void;
}) {
  const ids = { owner: useId(), client: useId(), category: useId(), q: useId() };
  const clients = useClients({ is_active: "true" });
  const categories = useProductCategories();

  return (
    <div className="filters panel">
      <Field label={strings.filterOwner} htmlFor={ids.owner}>
        <Select
          id={ids.owner}
          value={filters.owner ?? ""}
          placeholder={strings.filterOwnerAll}
          options={[{ value: "me", label: strings.filterOwnerMine }]}
          onChange={(event) => onChange("owner", event.target.value)}
        />
      </Field>

      <Field label={strings.filterClient} htmlFor={ids.client}>
        <Select
          id={ids.client}
          value={filters.client ?? ""}
          placeholder={strings.filterClientAll}
          options={(clients.data?.items ?? []).map((client) => ({
            value: client.id,
            label: client.legal_name,
          }))}
          onChange={(event) => onChange("client", event.target.value)}
        />
      </Field>

      <Field label={strings.filterCategory} htmlFor={ids.category}>
        <Select
          id={ids.category}
          value={filters.category ?? ""}
          placeholder={strings.filterCategoryAll}
          options={(categories.data ?? []).map((category) => ({
            value: category.id,
            label: category.name,
          }))}
          onChange={(event) => onChange("category", event.target.value)}
        />
      </Field>

      <Field label={strings.search} htmlFor={ids.q}>
        <input
          id={ids.q}
          className="input"
          type="search"
          defaultValue={filters.q ?? ""}
          placeholder={strings.searchPlaceholder}
          onChange={(event) => onChange("q", event.target.value)}
        />
      </Field>
    </div>
  );
}

function sortedColumns(board: Board) {
  return [...board.columns].sort((a, b) => a.stage.sequence_no - b.stage.sequence_no);
}

/** Columns come from the payload, in `sequence_no` order. Nothing here knows a stage code. */
function DeskBoard({ board }: { board: Board }) {
  if (board.total_lines === 0) {
    return (
      <div className="panel">
        <EmptyState title={strings.emptyBoard} />
      </div>
    );
  }

  return (
    <div className="board">
      {sortedColumns(board).map(({ stage, lines }) => (
        <Column key={stage.id} stage={stage} lines={lines} />
      ))}
    </div>
  );
}

function Column({ stage, lines }: { stage: Stage; lines: JobLineSummary[] }) {
  return (
    <section
      className="board__column"
      aria-label={`${stage.name}, ${strings.lineCount(lines.length)}`}
    >
      <header className="board__column-head">
        <h2 className="board__column-title">{stage.name}</h2>
        <span className="board__column-count">{lines.length}</span>
      </header>
      <div className="board__column-body">
        {lines.length === 0 ? (
          <p className="faint">{strings.emptyColumn}</p>
        ) : (
          lines.map((line) => <LineCard key={line.id} line={line} currentStage={stage} />)
        )}
      </div>
    </section>
  );
}

/** On a phone the columns become a stage selector over a single scrolling list. */
function PhoneBoard({ board }: { board: Board }) {
  const columns = sortedColumns(board);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = columns.find((column) => column.stage.id === selectedId) ?? columns[0];

  if (!selected) return <EmptyState title={strings.emptyBoard} />;

  return (
    <div className="stack stack--tight">
      {/* A plain button group, not a tablist: there's no paired tabpanel and no
          roving-tabindex arrow-key navigation, so claiming role="tab" would promise
          keyboard behavior this widget doesn't have. aria-pressed on each button is the
          complete, correct pattern for "which of these is currently selected." A
          <fieldset>/<legend> is the semantic element for a labelled group of controls —
          Biome's a11y lint flags role="group" on a bare div for exactly this. */}
      <fieldset className="stage-tabs">
        <legend className="visually-hidden">{strings.stageSelector}</legend>
        {columns.map(({ stage, lines }) => {
          const active = stage.id === selected.stage.id;
          return (
            <button
              key={stage.id}
              type="button"
              aria-pressed={active}
              className={cx("btn", "btn--sm", active && "btn--primary")}
              onClick={() => setSelectedId(stage.id)}
            >
              {stage.name} ({lines.length})
            </button>
          );
        })}
      </fieldset>

      <div className="board board--phone">
        <Column stage={selected.stage} lines={selected.lines} />
      </div>
    </div>
  );
}
