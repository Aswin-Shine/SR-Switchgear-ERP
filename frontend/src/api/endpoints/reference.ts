import { useQuery } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../queryKeys";
import type { EnumChoice, Enums, Me, ProductCategory, Stage } from "../types";

/**
 * Reference data: identity, the CHECK-constrained vocabularies, the stage list and the
 * product categories. All of it is data the administrator owns, none of it is compiled in.
 * It changes rarely, so it is cached for the session rather than refetched per screen.
 */
const REFERENCE_STALE_MS = 30 * 60 * 1000;

export function fetchMe(signal?: AbortSignal) {
  return api.get<Me>("/me", undefined, signal);
}

export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: ({ signal }) => fetchMe(signal),
    staleTime: REFERENCE_STALE_MS,
    retry: false, // a 401 here means "log in", not "try again"
  });
}

export function useEnums() {
  return useQuery({
    queryKey: queryKeys.enums,
    queryFn: ({ signal }) => api.get<Enums>("/enums", undefined, signal),
    staleTime: REFERENCE_STALE_MS,
  });
}

/** Choices for one CHECK-constrained domain, e.g. `dispatch_policy`. */
export function useEnumChoices(domain: string): EnumChoice[] {
  const { data } = useEnums();
  return data?.[domain] ?? [];
}

/** apps/pipeline/api.py::stages returns {module_code, items}. */
export function useStages() {
  return useQuery({
    queryKey: queryKeys.stages,
    queryFn: async ({ signal }) => {
      const body = await api.get<{ items: Stage[] }>("/pipeline/stages", undefined, signal);
      return [...body.items].sort((a, b) => a.sequence_no - b.sequence_no);
    },
    staleTime: REFERENCE_STALE_MS,
  });
}

/** apps/sales/api.py::product_categories returns {items}. */
export function useProductCategories() {
  return useQuery({
    queryKey: queryKeys.productCategories,
    queryFn: async ({ signal }) => {
      const body = await api.get<{ items: ProductCategory[] }>(
        "/product-categories",
        undefined,
        signal,
      );
      return body.items;
    },
    staleTime: REFERENCE_STALE_MS,
  });
}
