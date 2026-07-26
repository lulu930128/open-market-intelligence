import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createApiRequestId,
  createHttpApiError,
} from "@/lib/api";

const STREAM_CONNECT_TIMEOUT_MS = 20_000;
const STREAM_IDLE_TIMEOUT_MS = 150_000;

export type OmiSseMessage = {
  event: string;
  data: unknown;
};

export type OmiAskStreamHandlers = {
  onMessage?: (message: OmiSseMessage) => void;
  onDone?: () => void;
  onError?: (error: Error) => void;
  onAbort?: () => void;
};

function parseSseBlock(block: string): OmiSseMessage | null {
  let event = "message";
  const dataLines: string[] = [];

  block.split(/\r?\n/).forEach((rawLine) => {
    if (!rawLine || rawLine.startsWith(":")) return;

    const separatorIndex = rawLine.indexOf(":");
    const field = separatorIndex === -1 ? rawLine : rawLine.slice(0, separatorIndex);
    const value =
      separatorIndex === -1 ? "" : rawLine.slice(separatorIndex + 1).replace(/^ /, "");

    if (field === "event") event = value;
    if (field === "data") dataLines.push(value);
  });

  if (dataLines.length === 0 && event === "message") return null;

  const dataText = dataLines.join("\n");
  if (!dataText) return { event, data: {} };

  try {
    return { event, data: JSON.parse(dataText) as unknown };
  } catch {
    return { event, data: dataText };
  }
}

export function parseOmiSseBuffer(buffer: string) {
  const blocks = buffer.split(/\r?\n\r?\n/);
  const remainder = blocks.pop() ?? "";
  const messages = blocks
    .map((block) => parseSseBlock(block))
    .filter((message): message is OmiSseMessage => message !== null);

  return { messages, remainder };
}

export function useOmiAskStream(streamPath: string) {
  const abortRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);
  const [isStreaming, setIsStreaming] = useState(false);

  const stop = useCallback(() => {
    requestIdRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
  }, []);

  const ask = useCallback(
    async (
      requestBody: Record<string, unknown>,
      handlers: OmiAskStreamHandlers = {}
    ) => {
      abortRef.current?.abort();
      requestIdRef.current += 1;

      const requestId = requestIdRef.current;
      const abortController = new AbortController();
      const apiRequestId = createApiRequestId();
      let watchdogError: ApiError | null = null;
      abortRef.current = abortController;
      setIsStreaming(true);

      try {
        const connectTimeoutId = window.setTimeout(() => {
          watchdogError = new ApiError({
            kind: "timeout",
            message: `OMI stream connection timed out after ${STREAM_CONNECT_TIMEOUT_MS}ms.`,
            path: streamPath,
            requestId: apiRequestId,
          });
          abortController.abort();
        }, STREAM_CONNECT_TIMEOUT_MS);
        let response: Response;

        try {
          response = await fetch(streamPath, {
            method: "POST",
            headers: {
              Accept: "text/event-stream",
              "Content-Type": "application/json",
              "x-request-id": apiRequestId,
            },
            cache: "no-store",
            signal: abortController.signal,
            body: JSON.stringify(requestBody),
          });
        } finally {
          window.clearTimeout(connectTimeoutId);
        }

        if (!response.ok) {
          throw await createHttpApiError(response, streamPath);
        }

        if (!response.body) {
          throw new ApiError({
            kind: "invalid_response",
            message: "OMI did not return a readable stream.",
            path: streamPath,
            status: response.status,
            requestId: response.headers.get("x-request-id") || apiRequestId,
          });
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const idleTimeoutId = window.setTimeout(() => {
            watchdogError = new ApiError({
              kind: "timeout",
              message: `OMI stream was idle for ${STREAM_IDLE_TIMEOUT_MS}ms.`,
              path: streamPath,
              requestId: apiRequestId,
            });
            abortController.abort();
          }, STREAM_IDLE_TIMEOUT_MS);
          let readResult: ReadableStreamReadResult<Uint8Array>;

          try {
            readResult = await reader.read();
          } finally {
            window.clearTimeout(idleTimeoutId);
          }

          const { done, value } = readResult;
          if (done) break;
          if (requestId !== requestIdRef.current) return;

          buffer += decoder.decode(value, { stream: true });
          const { messages, remainder } = parseOmiSseBuffer(buffer);
          buffer = remainder;
          messages.forEach((message) => handlers.onMessage?.(message));
        }

        if (requestId !== requestIdRef.current) return;

        buffer += decoder.decode();
        const { messages } = parseOmiSseBuffer(`${buffer}\n\n`);
        messages.forEach((message) => handlers.onMessage?.(message));
        handlers.onDone?.();
      } catch (error) {
        if (watchdogError) {
          handlers.onError?.(watchdogError);
          return;
        }
        if (abortController.signal.aborted) {
          handlers.onAbort?.();
          return;
        }

        const normalizedError =
          error instanceof ApiError
            ? error
            : new ApiError({
                kind: "network",
                message:
                  error instanceof Error ? error.message : "OMI stream network error.",
                path: streamPath,
                requestId: apiRequestId,
              });
        handlers.onError?.(normalizedError);
      } finally {
        if (requestId === requestIdRef.current) {
          abortRef.current = null;
          setIsStreaming(false);
        }
      }
    },
    [streamPath]
  );

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  return {
    ask,
    isStreaming,
    stop,
  };
}
