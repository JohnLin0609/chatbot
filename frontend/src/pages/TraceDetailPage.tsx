import { Fragment, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import * as api from "../api/client";
import type { PromptSegment, TraceDetail } from "../api/types";
import NavBar from "../components/NavBar";
import { Stat } from "../components/charts";
import { Button, errorMessage } from "../components/ui";

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : v.toFixed(2);
const ms = (v: number | null) => (v === null ? "—" : `${Math.round(v)}ms`);

// per-layer accent so the prompt structure reads at a glance.
const KIND_COLOR: Record<string, string> = {
  system_prompt: "border-l-indigo-400",
  channel_summary: "border-l-sky-400",
  user_memory: "border-l-emerald-400",
  rag_knowledge: "border-l-amber-400",
  history: "border-l-gray-300",
  current_query: "border-l-rose-400",
  system_other: "border-l-gray-300",
};

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border bg-white p-4">
      <h2 className="mb-3 text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function SegmentCard({ seg }: { seg: PromptSegment }) {
  return (
    <div className={`rounded-md border border-l-4 bg-white p-3 ${KIND_COLOR[seg.kind] ?? "border-l-gray-300"}`}>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-sm font-medium">{seg.label}</span>
        <span className="text-xs text-gray-500 tabular-nums">
          {seg.tokens} tok · {Math.round(seg.pct * 100)}%
        </span>
      </div>
      {seg.turns ? (
        <div className="space-y-1">
          {seg.turns.map((t, i) => (
            <div key={i} className="text-sm">
              <span className="text-gray-400">{t.role}: </span>
              <span className="whitespace-pre-wrap">{t.content}</span>
            </div>
          ))}
        </div>
      ) : (
        <pre className="whitespace-pre-wrap break-words text-sm text-gray-800">
          {seg.content || <span className="text-gray-400">(empty)</span>}
        </pre>
      )}
    </div>
  );
}

export default function TraceDetailPage() {
  const { id } = useParams();
  const [data, setData] = useState<TraceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api
      .getTrace(Number(id))
      .then(setData)
      .catch((e) => setError(errorMessage(e)));
  }, [id]);

  if (error) {
    return (
      <div className="flex h-full flex-col">
        <NavBar />
        <p className="p-6 text-sm text-red-600">{error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="flex h-full flex-col">
        <NavBar />
        <p className="p-6 text-sm text-gray-400">Loading…</p>
      </div>
    );
  }

  const t = data.trace;
  const judge = data.judge;

  const copyJson = () => {
    if (!data.messages) return;
    navigator.clipboard?.writeText(JSON.stringify(data.messages, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="flex h-full flex-col">
      <NavBar />
      <div className="flex-1 space-y-5 overflow-y-auto p-6">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold">Trace #{t.id}</h1>
          <Link to="/admin/eval/traces" className="text-sm text-brand hover:underline">
            ← all traces
          </Link>
        </div>

        {/* metadata */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Tier" value={`${t.rag_tier ?? "—"}${t.reranked ? " ⚡" : ""}`} />
          <Stat label="Model" value={t.model ?? "—"} hint={t.provider ?? undefined} />
          <Stat label="Prompt tok" value={t.prompt_tokens === null ? "—" : String(t.prompt_tokens)} />
          <Stat label="Completion tok" value={t.completion_tokens === null ? "—" : String(t.completion_tokens)} />
          <Stat label="Retrieval" value={ms(t.retrieval_latency_ms)} />
          <Stat label="Generation" value={ms(t.generation_latency_ms)} />
        </div>
        <div className="text-xs text-gray-500">
          {(t.created_at ?? "").replace("T", " ").slice(0, 19)} · user {t.user_id ?? "—"} ·{" "}
          {t.session_key ?? "—"}
        </div>

        {/* prompt structure */}
        <Panel title="Prompt structure">
          {!data.bodies_logged ? (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
              Message bodies were not logged for this trace
              (<code>eval_log_message_bodies=false</code>). Token counts and metadata
              are still available above.
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex justify-end">
                <Button
                  className="bg-gray-200 text-gray-700 hover:bg-gray-300"
                  disabled={!data.messages}
                  onClick={copyJson}
                >
                  {copied ? "Copied ✓" : "Copy raw messages JSON"}
                </Button>
              </div>
              {data.segments.map((seg, i) => (
                <SegmentCard key={i} seg={seg} />
              ))}
              {/* output */}
              <div className="rounded-md border border-l-4 border-l-green-500 bg-green-50/40 p-3">
                <div className="mb-1 text-sm font-medium">Reply (output)</div>
                <pre className="whitespace-pre-wrap break-words text-sm text-gray-800">
                  {t.reply_text || <span className="text-gray-400">(empty)</span>}
                </pre>
              </div>
            </div>
          )}
        </Panel>

        {/* retrieval candidates */}
        <Panel title="Retrieval candidates">
          {data.chunks.length === 0 ? (
            <p className="text-sm text-gray-400">
              No retrieval for this turn (simple tier or retrieval disabled).
            </p>
          ) : (
            <table className="w-full text-sm" aria-label="retrieval candidates">
              <thead>
                <tr className="border-b text-left text-gray-500">
                  <th className="py-1 pr-3">doc / title</th>
                  <th className="py-1 pr-3">#</th>
                  <th className="py-1 pr-3">fused</th>
                  <th className="py-1 pr-3">f.rank</th>
                  <th className="py-1 pr-3">rerank</th>
                  <th className="py-1 pr-3">final</th>
                  <th className="py-1 pr-3">in</th>
                </tr>
              </thead>
              <tbody>
                {data.chunks.map((c) => (
                  <Fragment key={c.id}>
                    <tr
                      onClick={() => setOpen((o) => ({ ...o, [c.id]: !o[c.id] }))}
                      className={`cursor-pointer border-b hover:bg-gray-50 ${c.included ? "" : "text-gray-400"}`}
                    >
                      <td className="py-1 pr-3">
                        {c.title || c.doc_id || "—"}
                        {c.content_type === "code" && (
                          <span className="ml-1 rounded bg-amber-100 px-1 text-xs text-amber-700">
                            {c.paired ? "code · paired" : "code"}
                          </span>
                        )}
                      </td>
                      <td className="py-1 pr-3 tabular-nums">{c.chunk_index ?? "—"}</td>
                      <td className="py-1 pr-3 tabular-nums">{pct(c.fused_score)}</td>
                      <td className="py-1 pr-3 tabular-nums">{c.fused_rank ?? "—"}</td>
                      <td className="py-1 pr-3 tabular-nums">{pct(c.rerank_score)}</td>
                      <td className="py-1 pr-3 tabular-nums">{c.final_rank ?? "—"}</td>
                      <td className="py-1 pr-3">{c.included ? "✓" : ""}</td>
                    </tr>
                    {open[c.id] && (
                      <tr className="border-b bg-gray-50">
                        <td colSpan={7} className="px-3 py-2">
                          <pre className="whitespace-pre-wrap break-words text-xs text-gray-700">
                            {c.chunk_text || "(text not logged)"}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        {/* judge */}
        <Panel title="LLM-as-judge">
          {!judge ? (
            <p className="text-sm text-gray-400">
              Not judged yet — run the judge to score this trace.
            </p>
          ) : (
            <div className="space-y-3">
              <div className="text-xs text-gray-500">
                run {judge.run_id} · {judge.model ?? "—"}
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                {judge.metrics.map((m) => (
                  <div key={m.metric} className="rounded-lg border px-3 py-2">
                    <div className="text-xs text-gray-500">{m.metric.replace(/_/g, " ")}</div>
                    <div className="text-xl font-semibold tabular-nums">{pct(m.score)}</div>
                    {m.reasoning && (
                      <div className="mt-1 text-xs text-gray-500">{m.reasoning}</div>
                    )}
                  </div>
                ))}
              </div>
              {judge.chunk_labels.length > 0 && (
                <table className="w-full text-sm" aria-label="chunk relevance labels">
                  <thead>
                    <tr className="border-b text-left text-gray-500">
                      <th className="py-1 pr-3">chunk</th>
                      <th className="py-1 pr-3">relevance</th>
                      <th className="py-1 pr-3">why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {judge.chunk_labels.map((l, i) => (
                      <tr key={i} className="border-b">
                        <td className="py-1 pr-3">{l.title ?? l.chunk_ref_id}</td>
                        <td className="py-1 pr-3 tabular-nums">{pct(l.relevance)}</td>
                        <td className="py-1 pr-3 text-gray-500">{l.reasoning ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
