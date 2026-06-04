import { useEffect, useState } from "react";

import * as api from "../api/client";
import NavBar from "../components/NavBar";
import { Button, errorMessage } from "../components/ui";

export default function SystemPromptPage() {
  const [prompt, setPrompt] = useState("");
  const [isDefault, setIsDefault] = useState(true);
  const [defaultPrompt, setDefaultPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function load() {
    try {
      const r = await api.getSystemPrompt();
      setPrompt(r.prompt);
      setIsDefault(r.is_default);
      setDefaultPrompt(r.default);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function save(value: string) {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const r = await api.setSystemPrompt(value);
      setPrompt(r.prompt);
      setIsDefault(r.is_default);
      setSaved(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <NavBar />
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-2xl space-y-4">
          <div>
            <h2 className="text-lg font-semibold">System prompt</h2>
            <p className="text-sm text-gray-500">
              Define the agent's role for every conversation. Saving an empty
              prompt resets to the server default.{" "}
              {isDefault ? (
                <span className="text-gray-400">(currently using default)</span>
              ) : (
                <span className="text-brand">(custom override active)</span>
              )}
            </p>
          </div>

          <textarea
            value={prompt}
            onChange={(e) => {
              setPrompt(e.target.value);
              setSaved(false);
            }}
            rows={10}
            className="w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-sm focus:border-brand focus:outline-none"
            placeholder="You are a helpful assistant…"
          />

          {error && <p className="text-sm text-red-600">{error}</p>}
          {saved && <p className="text-sm text-green-600">Saved.</p>}

          <div className="flex gap-2">
            <Button onClick={() => save(prompt)} disabled={busy}>
              Save
            </Button>
            <button
              onClick={() => save("")}
              disabled={busy}
              className="rounded-md border px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50"
            >
              Reset to default
            </button>
          </div>

          <details className="text-sm text-gray-500">
            <summary className="cursor-pointer">Server default</summary>
            <pre className="mt-2 whitespace-pre-wrap rounded bg-gray-50 p-3 font-mono text-xs">
              {defaultPrompt}
            </pre>
          </details>
        </div>
      </div>
    </div>
  );
}
