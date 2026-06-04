import { useCallback, useEffect, useState } from "react";

import * as api from "../api/client";
import type { DocumentMeta } from "../api/types";
import NavBar from "../components/NavBar";
import DocTable from "../components/DocTable";
import UploadPanel from "../components/UploadPanel";
import ChunkInspector from "../components/ChunkInspector";
import { errorMessage } from "../components/ui";

export default function AdminPage() {
  const [docs, setDocs] = useState<DocumentMeta[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setDocs(await api.listDocuments());
    } catch (e) {
      setError(errorMessage(e));
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
