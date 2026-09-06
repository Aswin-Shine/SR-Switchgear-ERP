import { api } from "@/api/client";
import { useClient, useClients, useCreateClient, useCreateContact } from "@/api/endpoints/clients";
import { useCreateJobCard } from "@/api/endpoints/jobCards";
import { useEnumChoices, useProductCategories } from "@/api/endpoints/reference";
import { queryKeys } from "@/api/queryKeys";
import { Button } from "@/components/Button";
import { Combobox } from "@/components/Combobox";
import { Dialog } from "@/components/Dialog";
import { Field } from "@/components/Field";
import { PageHead } from "@/components/PageHead";
import { errorMessage } from "@/components/QueryState";
import { Select } from "@/components/Select";
import { useToast } from "@/components/Toast";
import { useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useId, useState } from "react";
import { useNavigate } from "react-router";
import { strings } from "./strings";

/** apps/sales/services.py::add_job_line has no "uom" field on JobLine at all, and
 * product_category is required, not optional — draft state mirrors that.
 *
 * No per-line required_by here on purpose: the form used to offer one alongside the
 * enquiry's own required_by, and the two could silently hold different dates with
 * nothing surfacing that they'd diverged (a hint that tried to explain it read as
 * developer-facing noise, not something a user asked for). One date, not two — every
 * line gets the enquiry's required_by at submission (see submit() below). */
interface DraftLine {
  key: string;
  description: string;
  product_category_id: string;
  quantity: string;
}

interface DraftRequirement {
  key: string;
  name: string;
  value: string;
}

function newKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : String(Math.random());
}

function blankLine(): DraftLine {
  return {
    key: newKey(),
    description: "",
    product_category_id: "",
    quantity: "1",
  };
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Enquiry intake. apps/sales/api.py::job_cards (POST) creates only the card — it never
 * reads a "lines" field — so a line is a separate POST per line, sent after the card
 * exists (see submit() below). There is also no "title" field on a job card anywhere in
 * the schema, so this form doesn't collect one.
 */
export function NewJobCardPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { push } = useToast();
  const create = useCreateJobCard();

  const ids = {
    client: useId(),
    contact: useId(),
    source: useId(),
    enquiryDate: useId(),
    requiredBy: useId(),
    dispatch: useId(),
  };

  const [clientQuery, setClientQuery] = useState("");
  const [clientId, setClientId] = useState<string | null>(null);
  const [contactId, setContactId] = useState<string>("");
  const [source, setSource] = useState("");
  const [enquiryDate, setEnquiryDate] = useState(today);
  const [requiredBy, setRequiredBy] = useState("");
  const [dispatchPolicy, setDispatchPolicy] = useState("");
  const [policyOverridden, setPolicyOverridden] = useState(false);
  const [requirements, setRequirements] = useState<DraftRequirement[]>([]);
  const [lines, setLines] = useState<DraftLine[]>(() => [blankLine()]);
  const [touched, setTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [creatingClientName, setCreatingClientName] = useState<string | null>(null);
  const [creatingContact, setCreatingContact] = useState(false);

  const clientResults = useClients({ q: clientQuery, is_active: "true" });
  const clientDetail = useClient(clientId ?? "", Boolean(clientId));
  const sources = useEnumChoices("enquiry_source");
  const policies = useEnumChoices("dispatch_policy");
  const categories = useProductCategories();

  const clientDefaultPolicy = clientDetail.data?.default_dispatch_policy ?? "";

  // Seed the policy from the client, and stop seeding the moment the user takes over.
  useEffect(() => {
    if (policyOverridden) return;
    setDispatchPolicy(clientDefaultPolicy);
  }, [clientDefaultPolicy, policyOverridden]);

  const errors = {
    client: clientId ? null : strings.clientRequired,
    lines: lines.every((line) => line.description.trim() && line.product_category_id)
      ? null
      : strings.lineDescriptionRequired,
  };
  const valid = !errors.client && !errors.lines;

  function updateLine(key: string, patch: Partial<DraftLine>) {
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...patch } : line)));
  }

  /** The card and its lines are two separate real endpoints (create_job_card never
   * accepts lines) — this sends the card first, then each line, in sequence, so a line
   * failure is reported against a card that already visibly exists rather than silently
   * losing the whole submission. */
  async function submit() {
    setTouched(true);
    if (!valid || !clientId || submitting) return;

    const requirementMap: Record<string, string> = {};
    for (const requirement of requirements) {
      const name = requirement.name.trim();
      if (name) requirementMap[name] = requirement.value.trim();
    }

    setSubmitting(true);
    try {
      const card = await create.mutateAsync({
        client_id: clientId,
        client_contact: contactId || null,
        enquiry_date: enquiryDate,
        required_by: requiredBy || null,
        enquiry_source: source || null,
        dispatch_policy: dispatchPolicy || null,
        requirements: requirementMap,
      });

      for (const line of lines) {
        await api.post(`/job-cards/${card.id}/lines`, {
          product_category_id: line.product_category_id,
          description: line.description.trim(),
          quantity: Number(line.quantity) || 1,
          // One required_by for the whole enquiry, not a per-line one — see the
          // DraftLine comment above.
          required_by: requiredBy || null,
        });
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobCard(card.id) });
      void queryClient.invalidateQueries({ queryKey: ["board"] });

      push({ tone: "success", title: strings.createdToast(card.job_no) });
      void navigate(`/job-cards/${card.id}`);
    } catch (error) {
      push({ tone: "error", title: strings.createFailed, detail: errorMessage(error) });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="stack">
      <PageHead
        title={strings.intakeTitle}
        subtitle={strings.intakeSubtitle}
        actions={
          <>
            <Button onClick={() => void navigate(-1)}>{strings.cancel}</Button>
            <Button variant="primary" onClick={() => void submit()} loading={submitting}>
              {submitting ? strings.saving : strings.save}
            </Button>
          </>
        }
      />

      <section className="panel">
        <div className="panel__head">
          <h2 className="panel__title">{strings.detailHeader}</h2>
        </div>
        <div className="panel__body grid-2">
          <Field
            label={strings.client}
            htmlFor={ids.client}
            required
            error={touched ? errors.client : null}
          >
            <Combobox
              id={ids.client}
              query={clientQuery}
              onQueryChange={(value) => {
                setClientQuery(value);
                setClientId(null);
              }}
              loading={clientResults.isFetching}
              invalid={touched && Boolean(errors.client)}
              placeholder={strings.clientPlaceholder}
              options={(clientResults.data?.items ?? []).map((client) => ({
                value: client.id,
                label: client.legal_name,
                meta: client.client_code,
              }))}
              onSelect={(option) => {
                setClientId(option.value);
                setClientQuery(option.label);
                setContactId("");
              }}
              createLabel={strings.clientCreate}
              onCreate={(name) => setCreatingClientName(name)}
            />
          </Field>

          <Field label={strings.contact} htmlFor={ids.contact}>
            <div className="row">
              <Select
                id={ids.contact}
                value={contactId}
                placeholder={strings.contactNone}
                disabled={!clientId}
                options={(clientDetail.data?.contacts ?? []).map((contact) => ({
                  value: contact.id,
                  label: contact.is_primary
                    ? `${contact.contact_name} (primary)`
                    : contact.contact_name,
                }))}
                onChange={(event) => setContactId(event.target.value)}
              />
              <Button
                size="sm"
                variant="ghost"
                disabled={!clientId}
                onClick={() => setCreatingContact(true)}
              >
                {strings.contactCreate}
              </Button>
            </div>
          </Field>

          <Field label={strings.source} htmlFor={ids.source}>
            <Select
              id={ids.source}
              value={source}
              placeholder={strings.sourceNone}
              options={sources}
              onChange={(event) => setSource(event.target.value)}
            />
          </Field>

          <Field label={strings.enquiryDate} htmlFor={ids.enquiryDate} required>
            <input
              id={ids.enquiryDate}
              className="input"
              type="date"
              value={enquiryDate}
              onChange={(event) => setEnquiryDate(event.target.value)}
            />
          </Field>

          <Field label={strings.requiredBy} htmlFor={ids.requiredBy}>
            <input
              id={ids.requiredBy}
              className="input"
              type="date"
              value={requiredBy}
              onChange={(event) => setRequiredBy(event.target.value)}
            />
          </Field>

          <Field label={strings.dispatchPolicy} htmlFor={ids.dispatch}>
            <Select
              id={ids.dispatch}
              value={dispatchPolicy}
              placeholder={strings.dispatchPolicyNone}
              options={policies}
              onChange={(event) => {
                setPolicyOverridden(true);
                setDispatchPolicy(event.target.value);
              }}
            />
          </Field>
        </div>
      </section>

      <section className="panel">
        <div className="panel__head">
          <h2 className="panel__title">{strings.requirements}</h2>
          <span className="panel__count">{requirements.length}</span>
          <Button
            size="sm"
            onClick={() =>
              setRequirements((current) => [...current, { key: newKey(), name: "", value: "" }])
            }
          >
            {strings.addRequirement}
          </Button>
        </div>
        <div className="panel__body stack stack--tight">
          <p className="field__hint">{strings.requirementsHint}</p>
          {requirements.map((requirement) => (
            <div className="row" key={requirement.key}>
              <input
                className="input"
                aria-label={strings.requirementKey}
                placeholder={strings.requirementKey}
                value={requirement.name}
                onChange={(event) =>
                  setRequirements((current) =>
                    current.map((item) =>
                      item.key === requirement.key ? { ...item, name: event.target.value } : item,
                    ),
                  )
                }
              />
              <input
                className="input"
                aria-label={strings.requirementValue}
                placeholder={strings.requirementValue}
                value={requirement.value}
                onChange={(event) =>
                  setRequirements((current) =>
                    current.map((item) =>
                      item.key === requirement.key ? { ...item, value: event.target.value } : item,
                    ),
                  )
                }
              />
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  setRequirements((current) =>
                    current.filter((item) => item.key !== requirement.key),
                  )
                }
              >
                {strings.removeRequirement}
              </Button>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel__head">
          <h2 className="panel__title">{strings.lines}</h2>
          <span className="panel__count">{lines.length}</span>
          <Button size="sm" onClick={() => setLines((current) => [...current, blankLine()])}>
            {strings.addLine}
          </Button>
        </div>
        <div className="panel__body stack">
          {lines.map((line, index) => (
            <Fragment key={line.key}>
              {index > 0 ? <hr className="divider" /> : null}
              <LineFields
                line={line}
                index={index}
                categories={categories.data ?? []}
                showError={touched && !line.description.trim()}
                onChange={(patch) => updateLine(line.key, patch)}
                onRemove={
                  lines.length > 1
                    ? () => setLines((current) => current.filter((item) => item.key !== line.key))
                    : undefined
                }
              />
            </Fragment>
          ))}
        </div>
      </section>

      {creatingClientName !== null ? (
        <NewClientDialog
          initialLegalName={creatingClientName}
          onClose={() => setCreatingClientName(null)}
          onCreated={(client) => {
            setClientId(client.id);
            setClientQuery(client.legal_name);
            setCreatingClientName(null);
          }}
        />
      ) : null}

      {creatingContact && clientId ? (
        <NewContactDialog
          clientId={clientId}
          onClose={() => setCreatingContact(false)}
          onCreated={(contact) => {
            setContactId(contact.id);
            setCreatingContact(false);
          }}
        />
      ) : null}
    </div>
  );
}

/** apps/sales/api.py::clients (POST) only requires legal_name — client_code is issued
 * server-side by apps.core.numbering.next_client_code(), never collected here. */
function NewClientDialog({
  initialLegalName,
  onClose,
  onCreated,
}: {
  initialLegalName: string;
  onClose: () => void;
  onCreated: (client: { id: string; legal_name: string }) => void;
}) {
  const ids = { legalName: useId() };
  const [legalName, setLegalName] = useState(initialLegalName);
  const [touched, setTouched] = useState(false);
  const createClient = useCreateClient();
  const { push } = useToast();

  const errors = {
    legalName: legalName.trim() ? null : strings.clientRequired,
  };
  const valid = !errors.legalName;

  function submit() {
    setTouched(true);
    if (!valid) return;
    createClient.mutate(
      { legal_name: legalName.trim() },
      {
        onSuccess: onCreated,
        onError: (error) =>
          push({ tone: "error", title: strings.clientCreate, detail: errorMessage(error) }),
      },
    );
  }

  return (
    <Dialog
      open
      title={strings.clientCreate}
      onClose={createClient.isPending ? () => undefined : onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={createClient.isPending}>
            {strings.clientCreateCancel}
          </Button>
          <Button variant="primary" onClick={submit} loading={createClient.isPending}>
            {strings.clientCreateSubmit}
          </Button>
        </>
      }
    >
      <Field
        label={strings.clientCreateLegalName}
        htmlFor={ids.legalName}
        required
        error={touched ? errors.legalName : null}
      >
        <input
          id={ids.legalName}
          className="input"
          value={legalName}
          aria-invalid={touched && Boolean(errors.legalName)}
          onChange={(event) => setLegalName(event.target.value)}
        />
      </Field>
    </Dialog>
  );
}

/** apps/sales/services.py::add_client_contact requires contact_name plus a phone or
 * an email (ck_client_contacts_reach) — no contact-update endpoint exists anywhere in
 * the backend, so a contact's is_primary can only be set here, at creation. */
function NewContactDialog({
  clientId,
  onClose,
  onCreated,
}: {
  clientId: string;
  onClose: () => void;
  onCreated: (contact: { id: string }) => void;
}) {
  const ids = { name: useId(), phone: useId(), email: useId(), primary: useId() };
  const [contactName, setContactName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [isPrimary, setIsPrimary] = useState(false);
  const [touched, setTouched] = useState(false);
  const createContact = useCreateContact(clientId);
  const { push } = useToast();

  const errors = {
    contactName: contactName.trim() ? null : strings.contactCreateNameRequired,
    reach: phone.trim() || email.trim() ? null : strings.contactCreateReachRequired,
  };
  const valid = !errors.contactName && !errors.reach;

  function submit() {
    setTouched(true);
    if (!valid) return;
    createContact.mutate(
      {
        contact_name: contactName.trim(),
        phone: phone.trim() || null,
        email: email.trim() || null,
        is_primary: isPrimary,
      },
      {
        onSuccess: onCreated,
        onError: (error) =>
          push({ tone: "error", title: strings.contactCreate, detail: errorMessage(error) }),
      },
    );
  }

  return (
    <Dialog
      open
      title={strings.contactCreate}
      onClose={createContact.isPending ? () => undefined : onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={createContact.isPending}>
            {strings.contactCreateCancel}
          </Button>
          <Button variant="primary" onClick={submit} loading={createContact.isPending}>
            {strings.contactCreateSubmit}
          </Button>
        </>
      }
    >
      <Field
        label={strings.contactCreateName}
        htmlFor={ids.name}
        required
        error={touched ? errors.contactName : null}
      >
        <input
          id={ids.name}
          className="input"
          value={contactName}
          aria-invalid={touched && Boolean(errors.contactName)}
          onChange={(event) => setContactName(event.target.value)}
        />
      </Field>

      <Field
        label={strings.contactCreatePhone}
        htmlFor={ids.phone}
        error={touched ? errors.reach : null}
      >
        <input
          id={ids.phone}
          className="input"
          value={phone}
          aria-invalid={touched && Boolean(errors.reach)}
          onChange={(event) => setPhone(event.target.value)}
        />
      </Field>

      <Field label={strings.contactCreateEmail} htmlFor={ids.email}>
        <input
          id={ids.email}
          className="input"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </Field>

      <label className="row" htmlFor={ids.primary}>
        <input
          id={ids.primary}
          type="checkbox"
          checked={isPrimary}
          onChange={(event) => setIsPrimary(event.target.checked)}
        />
        <span>{strings.contactCreatePrimary}</span>
      </label>
    </Dialog>
  );
}

function LineFields({
  line,
  index,
  categories,
  showError,
  onChange,
  onRemove,
}: {
  line: DraftLine;
  index: number;
  categories: { id: string; name: string }[];
  showError: boolean;
  onChange: (patch: Partial<DraftLine>) => void;
  onRemove?: () => void;
}) {
  const ids = {
    description: useId(),
    category: useId(),
    quantity: useId(),
  };

  return (
    <div className="stack stack--tight">
      <div className="row">
        <strong>
          {strings.colLine} {index + 1}
        </strong>
        <span className="filters__spacer" />
        {onRemove ? (
          <Button size="sm" variant="ghost" onClick={onRemove}>
            {strings.removeLine}
          </Button>
        ) : null}
      </div>

      <div className="grid-2">
        <Field
          label={strings.lineDescription}
          htmlFor={ids.description}
          required
          error={showError ? strings.lineDescriptionRequired : null}
        >
          <input
            id={ids.description}
            className="input"
            value={line.description}
            aria-invalid={showError}
            onChange={(event) => onChange({ description: event.target.value })}
          />
        </Field>

        <Field
          label={strings.lineCategory}
          htmlFor={ids.category}
          required
          error={showError && !line.product_category_id ? strings.lineDescriptionRequired : null}
        >
          <Select
            id={ids.category}
            value={line.product_category_id}
            placeholder={strings.lineCategoryNone}
            options={categories.map((category) => ({
              value: category.id,
              label: category.name,
            }))}
            onChange={(event) => onChange({ product_category_id: event.target.value })}
          />
        </Field>

        <Field label={strings.lineQty} htmlFor={ids.quantity} required>
          <input
            id={ids.quantity}
            className="input numeric"
            inputMode="decimal"
            value={line.quantity}
            onChange={(event) => onChange({ quantity: event.target.value })}
          />
        </Field>
      </div>
    </div>
  );
}
