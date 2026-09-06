/**
 * Fixture data for FE0: the board, the card detail and the intake form render from this
 * with no Django behind them. It is also what the component tests are built from.
 *
 * This file is dev/test only — api/client.ts imports the transport dynamically, and only
 * when VITE_API_MODE=fixtures, so none of it reaches a production bundle.
 *
 * The shapes here are the contract, matching the real backend's — see
 * backend/apps/sales/api.py and backend/apps/pipeline/api.py's serialize_* functions and
 * their pinned contract tests (backend/tests/contract/*.py). If a payload changes on the
 * server, it changes here too, and the mismatch shows up in the component tests before it
 * shows up in the office.
 */

import type {
  Attachment,
  ClientDetail,
  Enums,
  Me,
  Note,
  ProductCategory,
  Quotation,
  Stage,
} from "@/api/types";

export const me: Me = {
  id: "u-1",
  username: "rmenon",
  full_name: "Rakesh Menon",
  employee_id: "e-1",
  employee_code: "SR-014",
  department: "Sales",
  must_change_password: false,
  last_login: null,
  roles: [{ code: "sales_exec", name: "Sales Executive" }],
  grants: [
    { resource: "job_line", action: "view", level: 0, if_owner: false },
    { resource: "job_card", action: "view", level: 0, if_owner: false },
    { resource: "job_card", action: "create", level: 0, if_owner: true },
    { resource: "job_card", action: "edit", level: 0, if_owner: true },
    { resource: "job_line", action: "create", level: 0, if_owner: true },
    { resource: "job_line", action: "edit", level: 0, if_owner: true },
    { resource: "client", action: "view", level: 0, if_owner: false },
    { resource: "client", action: "create", level: 0, if_owner: false },
    { resource: "client", action: "edit", level: 0, if_owner: false },
    { resource: "quotation", action: "view", level: 0, if_owner: false },
    { resource: "quotation", action: "create", level: 0, if_owner: false },
    { resource: "quotation", action: "edit", level: 0, if_owner: false },
    { resource: "job_note", action: "create", level: 0, if_owner: false },
    { resource: "document", action: "create", level: 0, if_owner: false },
    { resource: "admin_site", action: "view", level: 0, if_owner: false },
  ],
};

/** apps/core/enums_api.py::DOMAINS — flat, no "enums" wrapper. */
export const enums: Enums = {
  job_lifecycle_status: [
    { value: "open", label: "Open" },
    { value: "quoted", label: "Quoted" },
    { value: "rework", label: "Rework" },
    { value: "won", label: "Won" },
    { value: "lost", label: "Lost" },
    { value: "cancelled", label: "Cancelled" },
  ],
  job_line_status: [
    { value: "active", label: "Active" },
    { value: "on_hold", label: "On hold" },
    { value: "completed", label: "Completed" },
    { value: "cancelled", label: "Cancelled" },
  ],
  quotation_status: [
    { value: "draft", label: "Draft" },
    { value: "superseded", label: "Superseded" },
  ],
  dispatch_policy: [
    { value: "partial_allowed", label: "Partial dispatch allowed" },
    { value: "complete_only", label: "Complete order only" },
  ],
  enquiry_source: [
    { value: "indiamart", label: "IndiaMART" },
    { value: "website", label: "Website" },
    { value: "phone", label: "Phone" },
    { value: "referral", label: "Referral" },
    { value: "walk_in", label: "Walk-in" },
    { value: "other", label: "Other" },
  ],
};

export const stages: Stage[] = [
  {
    id: "s-1",
    code: "ENQUIRY",
    name: "Enquiry",
    module_code: "sales_pipeline",
    sequence_no: 10,
    department: null,
    is_initial: true,
    is_terminal: false,
  },
  {
    id: "s-2",
    code: "QUOTATION",
    name: "Quotation",
    module_code: "sales_pipeline",
    sequence_no: 20,
    department: null,
    is_initial: false,
    is_terminal: false,
  },
  {
    id: "s-3",
    code: "NEGOTIATION",
    name: "Negotiation",
    module_code: "sales_pipeline",
    sequence_no: 30,
    department: null,
    is_initial: false,
    is_terminal: false,
  },
  {
    id: "s-4",
    code: "PRODUCTION",
    name: "Production",
    module_code: "sales_pipeline",
    sequence_no: 40,
    department: "Production",
    is_initial: false,
    is_terminal: false,
  },
  {
    id: "s-5",
    code: "DISPATCH",
    name: "Dispatch",
    module_code: "sales_pipeline",
    sequence_no: 50,
    department: null,
    is_initial: false,
    is_terminal: false,
  },
  {
    id: "s-6",
    code: "CLOSED",
    name: "Closed",
    module_code: "sales_pipeline",
    sequence_no: 60,
    department: null,
    is_initial: false,
    is_terminal: true,
  },
  {
    id: "s-7",
    code: "LOST",
    name: "Lost",
    module_code: "sales_pipeline",
    sequence_no: 70,
    department: null,
    is_initial: false,
    is_terminal: true,
  },
];

export const productCategories: ProductCategory[] = [
  { id: "c-1", code: "PANEL", name: "LT panel", is_manufactured: true },
  { id: "c-2", code: "MCC", name: "Motor control centre", is_manufactured: true },
  { id: "c-3", code: "SPARE", name: "Bought-out spare", is_manufactured: false },
];

export const clients: ClientDetail[] = [
  {
    id: "cl-1",
    client_code: "TATA-CH",
    legal_name: "Tata Projects, Chennai",
    billing_city: "Chennai",
    billing_state: "Tamil Nadu",
    gstin: "33AAACT2727Q1ZW",
    is_active: true,
    default_dispatch_policy: "complete_only",
    contacts: [
      {
        id: "ct-1",
        contact_name: "S Ravichandran",
        phone: "+91 98400 11223",
        email: "ravi@example.com",
        is_primary: true,
      },
      {
        id: "ct-2",
        contact_name: "Meera Iyer",
        phone: "+91 98400 55441",
        email: "meera@example.com",
        is_primary: false,
      },
    ],
  },
  {
    id: "cl-2",
    client_code: "KSEB",
    legal_name: "Kerala State Electricity Board",
    billing_city: "Thiruvananthapuram",
    billing_state: "Kerala",
    gstin: "32AAACK4160C1ZK",
    is_active: true,
    default_dispatch_policy: "partial_allowed",
    contacts: [
      {
        id: "ct-3",
        contact_name: "A Krishnan",
        phone: "+91 94470 33221",
        email: "krishnan@example.com",
        is_primary: true,
      },
    ],
  },
  {
    id: "cl-3",
    client_code: "BLUEST",
    legal_name: "Bluestar Engineering",
    billing_city: "Coimbatore",
    billing_state: "Tamil Nadu",
    gstin: null,
    is_active: false,
    default_dispatch_policy: "partial_allowed",
    contacts: [],
  },
];

/** An internal row — like a DB row, not any one wire shape. apps/sales/api.py projects
 * the real JobLine model into three different shapes depending on the endpoint
 * (serialize_job_line / serialize_board_line / job_line_detail); toJobLine / toBoardLine
 * / toLineDetail in transport.ts do the same thing here from one row. */
export interface FixtureLine {
  id: string;
  job_card_id: string;
  job_no: string;
  client: string;
  dispatch_policy: string;
  line_no: number;
  description: string;
  product_category: ProductCategory;
  quantity: number;
  line_status: string;
  required_by: string | null;
  specs: Record<string, string>;
  current_stage_id: string;
}

/** apps/sales/api.py::serialize_job_card's real fields — no title, no counts, no
 * quoted_amount; those never existed. */
export interface FixtureCard {
  id: string;
  job_no: string;
  client: { id: string; client_code: string; legal_name: string };
  client_contact: {
    id: string;
    contact_name: string;
    phone: string | null;
    email: string | null;
    is_primary: boolean;
  } | null;
  owner_user: { id: string; username: string };
  lifecycle_status: string;
  enquiry_source: string;
  dispatch_policy: string;
  enquiry_date: string;
  required_by: string | null;
  requirements: Record<string, string>;
}

export interface FixtureTransition {
  id: number;
  from_stage: string | null;
  to_stage: string;
  action_code: string;
  performed_by: string;
  performed_at: string;
  note: string | null;
}

export interface FixtureState {
  clients: ClientDetail[];
  cards: FixtureCard[];
  lines: FixtureLine[];
  notes: Record<string, Note[]>;
  attachments: Record<string, Attachment[]>;
  quotations: (Quotation & { job_card_id: string })[];
  /** Keyed by job line id, oldest first — the line's own history. */
  transitions: Record<string, FixtureTransition[]>;
}

const day = (offset: number): string =>
  new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);

const stamp = (offset: number): string => new Date(Date.now() + offset * 86_400_000).toISOString();

export function initialState(): FixtureState {
  const lines: FixtureLine[] = [
    {
      id: "jl-1",
      job_card_id: "jc-1",
      job_no: "JOB-2026-0001",
      client: "Tata Projects, Chennai",
      dispatch_policy: "complete_only",
      line_no: 1,
      description: "LT panel 1600A, form 4b, with ACB incomer",
      product_category: { id: "c-1", code: "PANEL", name: "LT panel", is_manufactured: true },
      quantity: 2,
      line_status: "active",
      required_by: day(24),
      specs: {
        Incomer: "1600A ACB, 50kA",
        Busbar: "Aluminium, 1600A",
        Enclosure: "IP54, floor mounted",
      },
      current_stage_id: "s-2",
    },
    {
      id: "jl-2",
      job_card_id: "jc-1",
      job_no: "JOB-2026-0001",
      client: "Tata Projects, Chennai",
      dispatch_policy: "complete_only",
      line_no: 2,
      description: "Spare feeder modules, 63A MCCB",
      product_category: {
        id: "c-3",
        code: "SPARE",
        name: "Bought-out spare",
        is_manufactured: false,
      },
      quantity: 12,
      line_status: "active",
      required_by: day(24),
      specs: { Rating: "63A", Make: "Any approved" },
      current_stage_id: "s-1",
    },
    {
      id: "jl-3",
      job_card_id: "jc-2",
      job_no: "JOB-2026-0002",
      client: "Kerala State Electricity Board",
      dispatch_policy: "partial_allowed",
      line_no: 1,
      description: "MCC for pump house, 8 feeders",
      product_category: {
        id: "c-2",
        code: "MCC",
        name: "Motor control centre",
        is_manufactured: true,
      },
      quantity: 1,
      line_status: "active",
      required_by: day(-2),
      specs: { Feeders: "8", Starter: "DOL up to 7.5kW" },
      current_stage_id: "s-4",
    },
    {
      id: "jl-4",
      job_card_id: "jc-3",
      job_no: "JOB-2026-0003",
      client: "Tata Projects, Chennai",
      dispatch_policy: "complete_only",
      line_no: 1,
      description: "Distribution board retrofit, 12 way",
      product_category: { id: "c-1", code: "PANEL", name: "LT panel", is_manufactured: true },
      quantity: 4,
      line_status: "active",
      required_by: day(40),
      specs: {},
      current_stage_id: "s-1",
    },
    {
      id: "jl-5",
      job_card_id: "jc-3",
      job_no: "JOB-2026-0003",
      client: "Tata Projects, Chennai",
      dispatch_policy: "complete_only",
      line_no: 2,
      description: "Cable termination kit",
      product_category: {
        id: "c-3",
        code: "SPARE",
        name: "Bought-out spare",
        is_manufactured: false,
      },
      quantity: 20,
      line_status: "active",
      required_by: day(40),
      specs: {},
      current_stage_id: "s-3",
    },
  ];

  return {
    clients: structuredClone(clients),
    cards: [
      {
        id: "jc-1",
        job_no: "JOB-2026-0001",
        client: { id: "cl-1", client_code: "TATA-CH", legal_name: "Tata Projects, Chennai" },
        client_contact: clients[0]?.contacts[0]
          ? {
              id: clients[0].contacts[0].id,
              contact_name: clients[0].contacts[0].contact_name,
              phone: clients[0].contacts[0].phone,
              email: clients[0].contacts[0].email,
              is_primary: clients[0].contacts[0].is_primary,
            }
          : null,
        owner_user: { id: "u-1", username: "rmenon" },
        lifecycle_status: "quoted",
        enquiry_source: "website",
        dispatch_policy: "complete_only",
        enquiry_date: day(-9),
        required_by: day(24),
        requirements: {
          Site: "Ambattur, Chennai",
          Inspection: "Third party, before dispatch",
        },
      },
      {
        id: "jc-2",
        job_no: "JOB-2026-0002",
        client: { id: "cl-2", client_code: "KSEB", legal_name: "Kerala State Electricity Board" },
        client_contact: clients[1]?.contacts[0]
          ? {
              id: clients[1].contacts[0].id,
              contact_name: clients[1].contacts[0].contact_name,
              phone: clients[1].contacts[0].phone,
              email: clients[1].contacts[0].email,
              is_primary: clients[1].contacts[0].is_primary,
            }
          : null,
        owner_user: { id: "u-2", username: "dsuresh" },
        lifecycle_status: "won",
        enquiry_source: "referral",
        dispatch_policy: "partial_allowed",
        enquiry_date: day(-60),
        required_by: day(-2),
        requirements: { Tender: "KSEB/2025/114" },
      },
      {
        id: "jc-3",
        job_no: "JOB-2026-0003",
        client: { id: "cl-1", client_code: "TATA-CH", legal_name: "Tata Projects, Chennai" },
        client_contact: null,
        owner_user: { id: "u-1", username: "rmenon" },
        lifecycle_status: "open",
        enquiry_source: "phone",
        dispatch_policy: "complete_only",
        enquiry_date: day(-1),
        required_by: day(40),
        requirements: {},
      },
    ],
    lines,
    notes: {
      "jc-1": [
        {
          id: "n-1",
          body: "Client wants the quotation split so the spares can be released early.",
          author: "rmenon",
          job_line_id: null,
          created_at: stamp(-4),
        },
      ],
      "jc-2": [],
      "jc-3": [],
    },
    attachments: {
      "jc-1": [
        {
          id: "at-1",
          label: "Enquiry PDF",
          filename: "enquiry-ambattur.pdf",
          mime_type: "application/pdf",
          byte_size: 284_193,
          job_line_id: null,
          attached_by: "rmenon",
          attached_at: stamp(-9),
        },
      ],
      "jc-2": [],
      "jc-3": [],
    },
    quotations: [
      {
        id: "q-1",
        job_card_id: "jc-1",
        quotation_no: "SR-Q-2026-0041",
        revision_no: 0,
        status: "superseded",
        supersedes_id: null,
        quoted_amount: "1920000.00",
        currency: "INR",
        valid_till: day(-1),
        has_pdf: true,
        prepared_by: "rmenon",
      },
      {
        id: "q-2",
        job_card_id: "jc-1",
        quotation_no: "SR-Q-2026-0041",
        revision_no: 1,
        status: "draft",
        supersedes_id: "q-1",
        quoted_amount: "1845000.00",
        currency: "INR",
        valid_till: day(14),
        has_pdf: true,
        prepared_by: "rmenon",
      },
    ],
    transitions: {
      "jl-1": [
        {
          id: 1,
          from_stage: "ENQUIRY",
          to_stage: "QUOTATION",
          action_code: "quote",
          performed_by: "rmenon",
          performed_at: stamp(-3),
          note: "Drawings received, quoting the panel only.",
        },
      ],
      "jl-3": [
        {
          id: 2,
          from_stage: "NEGOTIATION",
          to_stage: "PRODUCTION",
          action_code: "confirm",
          performed_by: "dsuresh",
          performed_at: stamp(-21),
          note: null,
        },
      ],
    },
  };
}
