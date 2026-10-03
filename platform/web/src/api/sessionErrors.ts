/**
 * Only a missing or expired session (401) should sign the user out.
 * A 403 is a per-resource denial; the page that requested it reports the error itself.
 */
export function endsSession(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { status?: unknown }).status === 401;
}
