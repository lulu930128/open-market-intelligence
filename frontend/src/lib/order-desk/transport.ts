import { ApiError, createApiRequestId } from "@/lib/api";
import { readDeskSnapshot, type DeskCommand, type DeskSnapshot } from "./contract";

const path = "/order-desk/transport";

async function request(init: RequestInit): Promise<DeskSnapshot> {
  const requestId = createApiRequestId();
  let response: Response;
  try {
    response = await fetch(path, { ...init, cache: "no-store", signal: AbortSignal.timeout(15_000),
      headers: { ...init.headers, "Content-Type": "application/json", "x-request-id": requestId } });
  } catch {
    throw new ApiError({ kind: "network", path, requestId,
      message: "FAKE_TRANSPORT_UNAVAILABLE：結果未確認，請讀回狀態；不要假定操作完成。" });
  }
  const data = await response.json();
  if (!response.ok) {
    throw new ApiError({ kind: "http", path, requestId, status: response.status, code: data.code,
      message: data.code || "EXECUTION_REQUEST_FAILED" });
  }
  return readDeskSnapshot(data);
}

export const openDemo = () => request({ method: "POST", body: JSON.stringify({ type: "open_demo" }) });
export const readDesk = (session: string) => request({ method: "GET", headers: { "x-desk-session": session } });
export const commandDesk = (session: string, command: DeskCommand) => request({ method: "POST", body: JSON.stringify({ session_id: session, command }) });
