/**
 * Server-side backend config.
 *
 * These are read in route handlers only, so neither the base URL nor the API key
 * is ever compiled into the browser bundle. Anything named NEXT_PUBLIC_* would be.
 */

export const BACKEND_BASE_URL =
  process.env.BACKEND_API_BASE_URL?.replace(/\/+$/, "") ?? "http://127.0.0.1:8000";

export function backendHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const key = process.env.API_KEY?.trim();
  return key ? { ...extra, "X-API-Key": key } : { ...extra };
}

/** Pass the backend's JSON straight through, preserving its status code. */
export function relay(response: Response): Response {
  return new Response(response.body, {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") ?? "application/json" },
  });
}

export function unreachable(error: unknown): Response {
  const detail =
    error instanceof Error
      ? `Could not reach the extraction API at ${BACKEND_BASE_URL}: ${error.message}`
      : `Could not reach the extraction API at ${BACKEND_BASE_URL}.`;
  return Response.json({ detail }, { status: 502 });
}
