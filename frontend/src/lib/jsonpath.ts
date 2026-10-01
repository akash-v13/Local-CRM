/** Read a value from JSON by dotted path ("items.0.sku"). Mirrors backend/app/domain/jsonpath.py. */
export function extract(data: unknown, path: string): { found: boolean; value: unknown } {
  let current: unknown = data;
  for (const segment of path.split(".")) {
    if (Array.isArray(current) && /^\d+$/.test(segment) && Number(segment) < current.length) {
      current = current[Number(segment)];
    } else if (current !== null && typeof current === "object" && segment in current) {
      current = (current as Record<string, unknown>)[segment];
    } else {
      return { found: false, value: undefined };
    }
  }
  return { found: true, value: current };
}
