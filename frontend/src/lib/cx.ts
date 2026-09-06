type ClassValue = string | false | null | undefined;

/** Joins class names, dropping the falsy ones. Small enough not to be a dependency. */
export function cx(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}
