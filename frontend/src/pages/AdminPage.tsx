import { useCallback, useEffect, useState } from "react";

import * as api from "../api/client";
import type { DocumentMeta, FeedbackSummary } from "../api/types";
import NavBar from "../components/NavBar";
import DocTable from "../components/DocTable";
import UploadPanel from "../components/UploadPanel";
import ChunkInspector from "../components/ChunkInspector";
import { errorMessage } from "../components/ui";

export default function AdminPage() {
  const [docs, setDocs] = useState<DocumentMeta[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<FeedbackSummary | null>(null);

  const refresh = useCallback(async () => {
    try {
      setDocs(await api.listDocuments());
    } catch (e) {
      setError(errorMessage(e));
    }
    try {
      setFeedback(await api.getFeedbackSummary());
    } catch {
      /* feedback panel is best-effort */
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function toggle(doc: DocumentMeta) {
    try {
      await api.toggleDocument(doc.doc_id, !doc.enabled);
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <div className="flex h-full flex-col">
      <NavBar />
      <div className="flex-1 space-y-6 overflow-y-auto p-6">
        <section>
          <h2 className="mb-2 text-lg font-semibold">Upload knowledge</h2>
          <UploadPanel onDone={refresh} />
        </section>

        {feedback && (
          <section>
            <h2 className="mb-2 text-lg font-semibold">User feedback</h2>
            <div className="mb-2 flex gap-4 text-sm">
              <span className="rounded bg-green-50 px-3 py-1 text-green-700">
                👍 {feedback.up}
              </span>
              <span className="rounded bg-red-50 px-3 py-1 text-red-700">
                👎 {feedback.down}
              </span>
            </div>
            {feedback.recent_negative.length > 0 && (
              <div>
                <p className="mb-1 text-sm text-gray-500">Recent 👎 replies</p>
                <ul className="space-y-1 text-sm">
                  {feedback.recent_negative.map((n) => (
                    <li
                      key={n.message_id}
                      className="truncate rounded border bg-white px-3 py-1.5 text-gray-700"
                      title={n.content}
                    >
                      {n.content}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}

        <section>
          <h2 className="mb-2 text-lg font-semibold">Documents</h2>
          {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
          <DocTable
            docs={docs}
            onToggle={toggle}
            onInspect={setSelected}
            selected={selected}
          />
        </section>

        {selected && (
          <section>
            <h2 className="mb-2 text-lg font-semibold">
              Chunks · {selected}
            </h2>
            <ChunkInspector docId={selected} />
          </section>
        )}
      </div>
    </div>
  );
}
