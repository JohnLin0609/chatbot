import { useEffect, useState } from "react";

import * as api from "../api/client";
import type { Chunk } from "../api/types";
import { errorMessage } from "./ui";

export default function ChunkInspector({ docId }: { docId: string }) {
  const [chunks, setChunks] = useState<Chunk[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setChunks(null);
    setError(null);
    api
      .getChunks(docId)
      .then((r) => {
        if (!cancelled) setChunks(r.chunks);
      })
      .catch((e) => {
        if (!cancelled) setError(errorMessage(e));
      });
    return () => {
      cancelled = true;
    };
  }, [docId]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!chunks) return <p className="text-sm text-gray-400">Loading chunks…</p>;
  if (!chunks.length) return <p className="text-sm text-gray-400">No chunks.</p>;

  return (
    <div className="grid gap-3 md:grid-cols-2">
      {chunks.map((c) => {
        const slide = c.metadata?.slide_number;
        return (
          <div
            key={c.chunk_index}
            data-testid="chunk-card"
            className="rounded-lg border bg-white p-3 text-sm"
          >
            <div className="mb-1 flex items-center gap-2 text-xs text-gray-500">
              <span className="rounded bg-gray-100 px-1.5 py-0.5">
                #{c.chunk_index}
              </span>
              {slide !== undefined && slide !== null && (
                <span>slide {String(slide)}</span>
              )}
              {c.title && <span className="truncate">{c.title}</span>}
              <span
                className={`ml-auto rounded px-1.5 py-0.5 ${
                  c.enabled
                    ? "bg-green-100 text-green-700"
                    : "bg-gray-200 text-gray-500"
                }`}
              >
                {c.enabled ? "enabled" : "disabled"}
              </span>
            </div>
            <p className="whitespace-pre-wrap text-gray-700">{c.text}</p>
          </div>
        );
      })}
    </div>
  );
}
