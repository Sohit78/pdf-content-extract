import { BACKEND_BASE_URL, backendHeaders, relay, unreachable } from "@/lib/backend";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const contentType = request.headers.get("content-type");
  if (!contentType?.includes("multipart/form-data")) {
    return Response.json({ detail: "Expected a multipart/form-data upload." }, { status: 400 });
  }

  try {
    // Stream the upload straight through rather than buffering it here; the
    // backend enforces its own size cap and answers with 413.
    const response = await fetch(`${BACKEND_BASE_URL}/v1/extract/file`, {
      method: "POST",
      headers: backendHeaders({ "Content-Type": contentType }),
      body: request.body,
      cache: "no-store",
      duplex: "half",
    } as RequestInit & { duplex: "half" });
    return relay(response);
  } catch (error) {
    return unreachable(error);
  }
}
