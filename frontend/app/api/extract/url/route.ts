import { BACKEND_BASE_URL, backendHeaders, relay, unreachable } from "@/lib/backend";

export const runtime = "nodejs";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ detail: "Request body must be JSON." }, { status: 400 });
  }

  try {
    const response = await fetch(`${BACKEND_BASE_URL}/v1/extract/url`, {
      method: "POST",
      headers: backendHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
      cache: "no-store",
    });
    return relay(response);
  } catch (error) {
    return unreachable(error);
  }
}
