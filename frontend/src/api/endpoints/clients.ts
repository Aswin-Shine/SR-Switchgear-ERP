import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../queryKeys";
import type { ClientDetail, ClientSummary, Contact, Paginated } from "../types";

export type ClientFilters = {
  q?: string;
  is_active?: string;
  page?: string;
};

export function useClients(filters: ClientFilters, enabled = true) {
  return useQuery({
    queryKey: queryKeys.clients(filters),
    queryFn: ({ signal }) => api.get<Paginated<ClientSummary>>("/clients", { ...filters }, signal),
    enabled,
  });
}

export function useClient(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.client(id),
    queryFn: ({ signal }) => api.get<ClientDetail>(`/clients/${id}`, undefined, signal),
    enabled: enabled && Boolean(id),
  });
}

/** apps/sales/services.py::create_client's _CLIENT_FIELDS — legal_name is required by
 * the view, the rest optional. client_code is deliberately absent: it is issued by
 * apps.core.numbering.next_client_code(), never caller-supplied. */
export interface NewClientInput {
  legal_name: string;
  billing_city?: string;
  billing_state?: string;
  gstin?: string;
  default_dispatch_policy?: string | null;
}

export function useCreateClient() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: NewClientInput) => api.post<ClientDetail>("/clients", input),
    onSuccess: (client) => {
      queryClient.setQueryData(queryKeys.client(client.id), client);
      void queryClient.invalidateQueries({ queryKey: ["clients"] });
    },
  });
}

export function useUpdateClient(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<NewClientInput> & { is_active?: boolean }) =>
      api.patch<ClientDetail>(`/clients/${id}`, patch),
    onSuccess: (client) => {
      queryClient.setQueryData(queryKeys.client(id), client);
      void queryClient.invalidateQueries({ queryKey: ["clients"] });
    },
  });
}

/** apps/sales/services.py::add_client_contact accepts exactly these — no "designation"
 * field exists on ClientContact at all. */
export interface ContactInput {
  contact_name: string;
  phone?: string | null;
  email?: string | null;
  is_primary?: boolean;
}

/**
 * Promoting a contact to primary demotes the previous one. That is the service's job:
 * the partial unique index rejects a second primary, it does not clear the first.
 *
 * There is no contact-update endpoint anywhere in the backend (checked
 * apps/sales/api_urls.py and services.py) — a contact can only be created, never edited,
 * so there's deliberately no useUpdateContact here.
 */
export function useCreateContact(clientId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: ContactInput) => api.post<Contact>(`/clients/${clientId}/contacts`, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.client(clientId) });
    },
  });
}
