/** Explicit fake preview seam. No production endpoint, broker or SDK binding. */
import { DESK_CONTRACT } from "@/lib/order-desk/contract";

export const runtime = "nodejs";

async function forward(request: Request) {
  const port = process.env.OMI_ORDER_DESK_FAKE_PORT;
  if (!port || !/^\d{4,5}$/.test(port) || Number(port) > 65535) {
    return Response.json({ code: "LIVE_NOT_DEPLOYED_FAKE_NOT_CONFIGURED" }, { status: 503 });
  }
  const target = new URL(`http://127.0.0.1:${port}/`);
  const session = request.headers.get("x-desk-session");
  if (request.method === "GET" && session) target.searchParams.set("session_id", session);
  try {
    if (request.method === "POST") {
      const probe = await fetch(new URL("/", target), { cache: "no-store", signal: AbortSignal.timeout(2_000) });
      const identity = await probe.json();
      if (!probe.ok || identity.contract !== DESK_CONTRACT || identity.mode !== "FAKE_ONLY" || identity.live_broker !== "NOT_DEPLOYED") {
        return Response.json({ code: "INVALID_FAKE_TRANSPORT" }, { status: 502 });
      }
    }
    const body = request.method === "POST" ? await request.text() : undefined;
    if (body && body.length > 65536) return Response.json({ code: "BODY_TOO_LARGE" }, { status: 413 });
    const response = await fetch(target, { method: request.method, body, cache: "no-store",
      headers: { "Content-Type": "application/json" }, signal: AbortSignal.timeout(12_000) });
    const data = await response.json();
    if (response.ok && (data.contract !== DESK_CONTRACT || data.mode !== "FAKE_ONLY" || data.live_broker !== "NOT_DEPLOYED")) {
      return Response.json({ code: "INVALID_FAKE_TRANSPORT" }, { status: 502 });
    }
    return Response.json(data, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ code: "FAKE_TRANSPORT_UNAVAILABLE_RESULT_UNCONFIRMED" }, { status: 503 });
  }
}

export const GET = forward;
export const POST = forward;
