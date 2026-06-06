import { useEffect, useState } from "react";

import * as api from "../api/client";
import type { Dashboard } from "../api/types";
import NavBar from "../components/NavBar";
import { Bars, Sparkline, Stat } from "../components/charts";
import { errorMessage } from "../components/ui";

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : v.toFixed(2);

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border bg-white p-4">
      <h2 className="mb-3 text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getDashboard().then(setData).catch((e) => setError(errorMessage(e)));
  }, []);

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

  const ks = data.k_values;
  const ov = data.overview;
  const gen = data.generation;
  const ret = data.retrieval;
  const cost = data.cost;
  const golden = data.golden;
  const lastK = String(ks[ks.length - 1]);

  return (
    <div className="flex h-full flex-col">
      <NavBar />
      <div className="flex-1 space-y-5 overflow-y-auto p-6">
        {/* overview */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Traces" value={String(ov.traces)} />
          <Stat label="Judged" value={String(ov.judged_traces)} />
          <Stat label="LLM calls" value={String(ov.llm_calls)} />
          <Stat label="Golden queries" value={String(ov.golden_queries)} />
          <Stat label="👍" value={String(ov.feedback_up)} />
          <Stat label="👎" value={String(ov.feedback_down)} />
        </div>

        {/* generation quality */}
        <Panel title="Generation quality (judge)">
          {gen.series.length === 0 ? (
            <p className="text-sm text-gray-400">No judgements yet — run the judge.</p>
          ) : (
            <div className="grid gap-4 sm:grid-cols-3">
              {(["faithfulness", "answer_relevance", "context_utilization"] as const).map((m) => (
                <div key={m} className="rounded-lg border px-3 py-2">
                  <div className="text-xs text-gray-500">{m.replace(/_/g, " ")}</div>
                  <div className="mb-1 text-xl font-semibold tabular-nums">
                    {pct(gen.current[m])}
                  </div>
                  <Sparkline values={gen.series.map((s) => s[m])} />
                </div>
              ))}
            </div>
          )}
        </Panel>

        {/* retrieval quality from judge labels */}
        <Panel title="Retrieval quality (judge labels, over retrieved set)">
          {!ret.current ? (
            <p className="text-sm text-gray-400">No chunk labels yet — run the judge.</p>
          ) : (
            <div className="grid gap-6 sm:grid-cols-3">
              <div>
                <div className="mb-1 text-xs text-gray-500">Precision@k</div>
                <Bars items={ks.map((k) => ({ label: `P@${k}`, value: ret.current!.precision[String(k)] ?? null }))} />
              </div>
              <div>
                <div className="mb-1 text-xs text-gray-500">NDCG@k</div>
                <Bars items={ks.map((k) => ({ label: `NDCG@${k}`, value: ret.current!.ndcg[String(k)] ?? null }))} />
              </div>
              <div>
                <Stat label="MRR" value={pct(ret.current.mrr)} />
                <div className="mt-2 text-xs text-gray-500">MRR over runs</div>
                <Sparkline values={ret.series.map((s) => s.mrr)} />
              </div>
            </div>
          )}
        </Panel>

        {/* cost & latency */}
        <Panel title="Cost & latency (by day)">
          <div className="grid gap-4 sm:grid-cols-3">
            <Stat label="Total LLM calls" value={String(cost.totals.calls)} />
            <Stat label="Total tokens" value={cost.totals.tokens.toLocaleString()} />
            <div className="rounded-lg border px-3 py-2">
              <div className="text-xs text-gray-500">Daily tokens</div>
              <Sparkline
                values={cost.series.map((s) => s.prompt_tokens + s.completion_tokens)}
                min={0}
                max={Math.max(1, ...cost.series.map((s) => s.prompt_tokens + s.completion_tokens))}
              />
            </div>
          </div>
          {cost.by_call_type.length > 0 && (
            <table className="mt-3 w-full text-sm" aria-label="cost by call type">
              <thead>
                <tr className="border-b text-left text-gray-500">
                  <th className="py-1 pr-3">call type</th>
                  <th className="py-1 pr-3">calls</th>
                  <th className="py-1 pr-3">tokens</th>
                  <th className="py-1 pr-3">avg latency (ms)</th>
                </tr>
              </thead>
              <tbody>
                {cost.by_call_type.map((r) => (
                  <tr key={r.call_type} className="border-b">
                    <td className="py-1 pr-3">{r.call_type}</td>
                    <td className="py-1 pr-3 tabular-nums">{r.calls}</td>
                    <td className="py-1 pr-3 tabular-nums">{r.tokens.toLocaleString()}</td>
                    <td className="py-1 pr-3 tabular-nums">
                      {r.avg_latency_ms === null ? "—" : Math.round(r.avg_latency_ms)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        {/* golden history */}
        <Panel title="Golden eval history">
          {golden.series.length === 0 ? (
            <p className="text-sm text-gray-400">No golden runs yet — author a set and Run eval.</p>
          ) : (
            <div className="grid gap-6 sm:grid-cols-3">
              <div>
                <div className="mb-1 text-xs text-gray-500">Recall@{lastK} over runs</div>
                <Sparkline values={golden.series.map((s) => s.aggregate?.recall?.[lastK] ?? null)} />
              </div>
              <div>
                <div className="mb-1 text-xs text-gray-500">Correctness over runs</div>
                <Sparkline values={golden.series.map((s) => s.aggregate?.correctness ?? null)} />
              </div>
              <table className="text-sm" aria-label="golden runs">
                <thead>
                  <tr className="border-b text-left text-gray-500">
                    <th className="py-1 pr-3">run</th>
                    <th className="py-1 pr-3">Recall@{lastK}</th>
                    <th className="py-1 pr-3">Correct</th>
                  </tr>
                </thead>
                <tbody>
                  {golden.series.slice(-6).map((s) => (
                    <tr key={s.run_id} className="border-b">
                      <td className="py-1 pr-3">#{s.run_id}</td>
                      <td className="py-1 pr-3 tabular-nums">{pct(s.aggregate?.recall?.[lastK])}</td>
                      <td className="py-1 pr-3 tabular-nums">{pct(s.aggregate?.correctness)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
