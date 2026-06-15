import { useCallback, useEffect, useRef, useState } from "react";

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

async function readErrorText(response: Response) {
  const text = await response.text();
  return text || response.statusText || "OMI request failed.";
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
      abortRef.current = abortController;
      setIsStreaming(true);

      try {
        const response = await fetch(streamPath, {
          method: "POST",
          headers: {
            Accept: "text/event-stream",
            "Content-Type": "application/json",
          },
          cache: "no-store",
          signal: abortController.signal,
          body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
          throw new Error(await readErrorText(response));
        }

        if (!response.body) {
          throw new Error("OMI did not return a readable stream.");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
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
        if (abortController.signal.aborted) {
          handlers.onAbort?.();
          return;
        }

        const normalizedError =
          error instanceof Error ? error : new Error("OMI request failed.");
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
