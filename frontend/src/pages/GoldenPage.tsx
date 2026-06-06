import { useCallback, useEffect, useState } from "react";

import * as api from "../api/client";
import type {
  Chunk,
  DocumentMeta,
  GoldenChunk,
  GoldenQuery,
  GoldenRun,
} from "../api/types";
import NavBar from "../components/NavBar";
import { Button, errorMessage } from "../components/ui";

const key = (docId: string, idx: number) => `${docId}:${idx}`;

export default function GoldenPage() {
  const [queries, setQueries] = useState<GoldenQuery[]>([]);
  const [docs, setDocs] = useState<DocumentMeta[]>([]);
  const [error, setError] = useState<string | null>(null);

  // editor state
  const [editId, setEditId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  // selected relevant chunks: "docId:idx" -> relevance grade
  const [selected, setSelected] = useState<Record<string, number>>({});
  // expanded doc -> its chunks
  const [openDoc, setOpenDoc] = useState<string | null>(null);
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [saving, setSaving] = useState(false);

  // eval run
  const [run, setRun] = useState<GoldenRun | null>(null);
  const [running, setRunning] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setQueries(await api.listGolden());
      setDocs(await api.listDocuments());
      const latest = await api.latestGoldenRun();
      if (latest && latest.run_id) setRun(latest);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function resetEditor() {
    setEditId(null);
    setQuery("");
    setReference("");
    setNotes("");
    setSelected({});
    setOpenDoc(null);
    setChunks([]);
  }

  function editQuery(q: GoldenQuery) {
    setEditId(q.id);
    setQuery(q.query);
    setReference(q.reference_answer ?? "");
    setNotes(q.notes ?? "");
    setSelected(
      Object.fromEntries(q.relevant_chunks.map((c) => [key(c.doc_id, c.chunk_index), c.relevance])),
    );
    setOpenDoc(null);
    setChunks([]);
  }

  async function openDocument(docId: string) {
    if (openDoc === docId) {
      setOpenDoc(null);
      return;
    }
    try {
      const r = await api.getChunks(docId);
      setChunks(r.chunks);
      setOpenDoc(docId);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  function toggleChunk(docId: string, idx: number) {
    setSelected((s) => {
      const k = key(docId, idx);
      const next = { ...s };
      if (k in next) delete next[k];
      else next[k] = 1;
      return next;
    });
  }

  function setGrade(docId: string, idx: number, grade: number) {
    setSelected((s) => ({ ...s, [key(docId, idx)]: grade }));
  }

  async function save() {
    if (!query.trim()) return;
    setSaving(true);
    setError(null);
    const relevant_chunks: GoldenChunk[] = Object.entries(selected).map(([k, rel]) => {
      const [doc_id, idx] = [k.slice(0, k.lastIndexOf(":")), k.slice(k.lastIndexOf(":") + 1)];
      return { doc_id, chunk_index: Number(idx), relevance: rel };
    });
    const body = {
      query: query.trim(),
      reference_answer: reference.trim() || null,
      notes: notes.trim() || null,
      relevant_chunks,
    };
    try {
      if (editId) await api.updateGolden(editId, body);
      else await api.createGolden(body);
      resetEditor();
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: number) {
    try {
      await api.deleteGolden(id);
      if (editId === id) resetEditor();
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function runEval() {
    setRunning(true);
    setError(null);
    try {
      setRun(await api.runGoldenEval());
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setRunning(false);
    }
  }

  const ks = run?.k_values ?? [1, 3, 5];
  const fmt = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : v.toFixed(2);

  return (
    <div className="flex h-full flex-col">
      <NavBar />
      <div className="flex-1 space-y-6 overflow-y-auto p-6">
        {error && <p className="text-sm text-red-600">{error}</p>}

        {/* editor */}
        <section className="rounded-lg border bg-white p-4">
          <h2 className="mb-2 text-lg font-semibold">
            {editId ? "Edit golden query" : "New golden query"}
          </h2>
          <div className="space-y-2">
            <textarea
              aria-label="query"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Question (e.g. How long do I have to request a refund?)"
              rows={2}
              className="w-full rounded-md border px-3 py-2 text-sm focus:border-brand focus:outline-none"
            />
            <textarea
              aria-label="reference answer"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="Reference answer (optional — required for Correctness)"
              rows={2}
              className="w-full rounded-md border px-3 py-2 text-sm focus:border-brand focus:outline-none"
            />
            <input
              aria-label="notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Notes (optional)"
              className="w-full rounded-md border px-3 py-2 text-sm focus:border-brand focus:outline-none"
            />
          </div>

          {/* chunk picker */}
          <div className="mt-3">
            <p className="mb-1 text-sm font-medium text-gray-700">
              Relevant chunks ({Object.keys(selected).length} selected)
            </p>
            <div className="rounded border">
              {docs.length === 0 && (
                <p className="p-2 text-sm text-gray-400">No documents ingested yet.</p>
              )}
              {docs.map((d) => (
                <div key={d.doc_id} className="border-b last:border-0">
                  <button
                    onClick={() => openDocument(d.doc_id)}
                    className="flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-gray-50"
                  >
                    <span>{d.title ?? d.doc_id}</span>
                    <span className="text-gray-400">{openDoc === d.doc_id ? "▾" : "▸"}</span>
                  </button>
                  {openDoc === d.doc_id &&
                    chunks.map((c) => {
                      const k = key(d.doc_id, c.chunk_index);
                      const on = k in selected;
                      return (
                        <div
                          key={c.chunk_index}
                          className="flex items-start gap-2 px-4 py-1.5 text-sm"
                        >
                          <input
                            type="checkbox"
                            aria-label={`chunk ${c.chunk_index}`}
                            checked={on}
                            onChange={() => toggleChunk(d.doc_id, c.chunk_index)}
                            className="mt-1"
                          />
                          <span className="flex-1 truncate text-gray-700" title={c.text}>
                            #{c.chunk_index} {c.text}
                          </span>
                          {on && (
                            <select
                              aria-label={`grade ${c.chunk_index}`}
                              value={selected[k]}
                              onChange={(e) =>
                                setGrade(d.doc_id, c.chunk_index, Number(e.target.value))
                              }
                              className="rounded border text-xs"
                            >
                              <option value={1}>rel 1</option>
                              <option value={2}>rel 2</option>
                              <option value={3}>rel 3</option>
                            </select>
                          )}
                        </div>
                      );
                    })}
                </div>
              ))}
            </div>
          </div>

          <div className="mt-3 flex gap-2">
            <Button onClick={save} disabled={saving || !query.trim()}>
              {editId ? "Update" : "Create"}
            </Button>
            {editId && (
              <button onClick={resetEditor} className="rounded-md border px-4 py-2 text-sm">
                Cancel
              </button>
            )}
          </div>
        </section>

        {/* existing queries */}
        <section>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Golden set ({queries.length})</h2>
            <Button onClick={runEval} disabled={running || queries.length === 0}>
              {running ? "Running…" : "Run eval"}
            </Button>
          </div>
          <div className="space-y-1">
            {queries.map((q) => (
              <div
                key={q.id}
                className="flex items-center justify-between rounded border bg-white px-3 py-2 text-sm"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{q.query}</div>
                  <div className="text-xs text-gray-500">
                    {q.relevant_chunks.length} relevant chunk(s)
                    {q.reference_answer ? " · has reference" : " · no reference"}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => editQuery(q)} className="text-brand hover:underline">
                    edit
                  </button>
                  <button onClick={() => remove(q.id)} className="text-red-600 hover:underline">
                    delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* results */}
        {run && run.aggregate && (
          <section>
            <h2 className="mb-2 text-lg font-semibold">
              Last run · {run.num_queries} queries
            </h2>
            <table className="w-full border-collapse text-sm" aria-label="eval results">
              <thead>
                <tr className="border-b text-left text-gray-500">
                  <th className="py-1 pr-3">query</th>
                  {ks.map((k) => (
                    <th key={k} className="py-1 pr-3">Recall@{k}</th>
                  ))}
                  <th className="py-1 pr-3">MRR</th>
                  <th className="py-1 pr-3">NDCG@{ks[ks.length - 1]}</th>
                  <th className="py-1 pr-3">Correct</th>
                </tr>
              </thead>
              <tbody>
                {(run.results ?? []).map((r) => {
                  const q = queries.find((x) => x.id === r.golden_query_id);
                  const lastK = String(ks[ks.length - 1]);
                  return (
                    <tr key={r.golden_query_id} className="border-b">
                      <td className="py-1 pr-3 max-w-xs truncate" title={q?.query}>
                        {q?.query ?? r.golden_query_id}
                      </td>
                      {ks.map((k) => (
                        <td key={k} className="py-1 pr-3">{fmt(r.metrics?.recall?.[String(k)])}</td>
                      ))}
                      <td className="py-1 pr-3">{fmt(r.metrics?.mrr)}</td>
                      <td className="py-1 pr-3">{fmt(r.metrics?.ndcg?.[lastK])}</td>
                      <td className="py-1 pr-3" title={r.correctness_reasoning ?? ""}>
                        {fmt(r.correctness)}
                      </td>
                    </tr>
                  );
                })}
                <tr className="font-medium">
                  <td className="py-1 pr-3">mean</td>
                  {ks.map((k) => (
                    <td key={k} className="py-1 pr-3">{fmt(run.aggregate.recall?.[String(k)])}</td>
                  ))}
                  <td className="py-1 pr-3">{fmt(run.aggregate.mrr)}</td>
                  <td className="py-1 pr-3">
                    {fmt(run.aggregate.ndcg?.[String(ks[ks.length - 1])])}
                  </td>
                  <td className="py-1 pr-3">{fmt(run.aggregate.correctness)}</td>
                </tr>
              </tbody>
            </table>
          </section>
        )}
      </div>
    </div>
  );
}
