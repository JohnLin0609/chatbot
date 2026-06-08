import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import * as api from "../api/client";
import type { TraceList } from "../api/types";
import NavBar from "../components/NavBar";
import { Button, Input, errorMessage } from "../components/ui";

const TIERS = ["", "simple", "medium", "complex"];
const PAGE = 25;

const fmtTime = (s: string | null) => (s ? s.replace("T", " ").slice(0, 19) : "—");
const num = (v: number | null) => (v === null || v === undefined ? "—" : String(v));

export default function TracesPage() {
  const nav = useNavigate();
  const [data, setData] = useState<TraceList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tier, setTier] = useState("");
  const [user, setUser] = useState("");
  const [session, setSession] = useState("");
  const [offset, setOffset] = useState(0);

  const load = useCallback(() => {
    setError(null);
    api
      .listTraces({
        tier: tier || undefined,
        user_id: user || undefined,
        session_key: session || undefined,
        limit: PAGE,
        offset,
      })
      .then(setData)
      .catch((e) => setError(errorMessage(e)));
  }, [tier, user, session, offset]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="flex h-full flex-col">
      <NavBar />
      <div className="flex-1 space-y-4 overflow-y-auto p-6">
        <h1 className="text-lg font-semibold">Eval traces</h1>

        {/* filters */}
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-gray-500">
            Tier
            <select
              className="mt-1 block rounded-md border border-gray-300 px-2 py-2 text-sm"
              value={tier}
              onChange={(e) => {
                setOffset(0);
                setTier(e.target.value);
              }}
            >
              {TIERS.map((t) => (
                <option key={t || "any"} value={t}>
                  {t || "any"}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-gray-500">
            User id
            <Input
              className="mt-1 w-32"
              value={user}
              onChange={(e) => setUser(e.target.value)}
              placeholder="e.g. 7"
            />
          </label>
          <label className="text-xs text-gray-500">
            Session key
            <Input
              className="mt-1 w-56"
              value={session}
              onChange={(e) => setSession(e.target.value)}
              placeholder="e.g. web:7:c1"
            />
          </label>
          <Button
            onClick={() => {
              setOffset(0);
              load();
            }}
          >
            Apply
          </Button>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}
        {!data && !error && <p className="text-sm text-gray-400">Loading…</p>}

        {data &&
          (data.traces.length === 0 ? (
            <p className="text-sm text-gray-400">No traces match.</p>
          ) : (
            <>
              <table className="w-full text-sm" aria-label="traces">
                <thead>
                  <tr className="border-b text-left text-gray-500">
                    <th className="py-1 pr-3">time</th>
                    <th className="py-1 pr-3">user</th>
                    <th className="py-1 pr-3">tier</th>
                    <th className="py-1 pr-3">tokens (p/c)</th>
                    <th className="py-1 pr-3">latency</th>
                    <th className="py-1 pr-3">query</th>
                  </tr>
                </thead>
                <tbody>
                  {data.traces.map((t) => (
                    <tr
                      key={t.id}
                      onClick={() => nav(`/admin/eval/traces/${t.id}`)}
                      className="cursor-pointer border-b hover:bg-gray-50"
                    >
                      <td className="py-1 pr-3 whitespace-nowrap text-gray-500">
                        {fmtTime(t.created_at)}
                      </td>
                      <td className="py-1 pr-3">{t.user_id ?? "—"}</td>
                      <td className="py-1 pr-3">
                        {t.rag_tier ?? "—"}
                        {t.reranked ? " ⚡" : ""}
                      </td>
                      <td className="py-1 pr-3 tabular-nums">
                        {num(t.prompt_tokens)}/{num(t.completion_tokens)}
                      </td>
                      <td className="py-1 pr-3 tabular-nums">
                        {t.total_latency_ms === null
                          ? "—"
                          : `${Math.round(t.total_latency_ms)}ms`}
                      </td>
                      <td className="max-w-md truncate py-1 pr-3">
                        {t.query_preview || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* pager */}
              <div className="flex items-center gap-3 text-sm text-gray-500">
                <Button
                  className="bg-gray-200 text-gray-700 hover:bg-gray-300"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE))}
                >
                  ‹ Prev
                </Button>
                <span>
                  {offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}
                </span>
                <Button
                  className="bg-gray-200 text-gray-700 hover:bg-gray-300"
                  disabled={offset + PAGE >= data.total}
                  onClick={() => setOffset(offset + PAGE)}
                >
                  Next ›
                </Button>
              </div>
            </>
          ))}
      </div>
    </div>
  );
}
