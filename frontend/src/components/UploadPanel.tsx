import { type FormEvent, useState } from "react";

import * as api from "../api/client";
import { Button, Input, errorMessage } from "./ui";

export default function UploadPanel({ onDone }: { onDone: () => void }) {
  const [tab, setTab] = useState<"text" | "pptx" | "code">("text");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [docType, setDocType] = useState("prose");
  const [file, setFile] = useState<File | null>(null);
  const [skipLeading, setSkipLeading] = useState(0);
  const [skipTrailing, setSkipTrailing] = useState(0);
  const [topic, setTopic] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const r =
        tab === "text"
          ? await api.ingestText(text, title, docType)
          : tab === "code"
            ? await api.ingestCode(file as File, title, topic)
            : await api.ingestPptx(file as File, title, skipLeading, skipTrailing);
      setMsg(`Ingested ${r.doc_id} (${r.chunks_ingested} chunks)`);
      setText("");
      setFile(null);
      onDone();
    } catch (err) {
      setMsg(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const tabBtn = (key: "text" | "pptx" | "code", label: string) => (
    <button
      type="button"
      onClick={() => setTab(key)}
      className={tab === key ? "font-semibold" : "text-gray-400"}
    >
      {label}
    </button>
  );

  return (
    <form onSubmit={submit} className="space-y-3 rounded-lg border bg-white p-4">
      <div className="flex gap-3 text-sm">
        {tabBtn("text", "Text")}
        {tabBtn("pptx", "Slides (.pptx)")}
        {tabBtn("code", "Code (.py)")}
      </div>
      <Input
        placeholder="Title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      {tab === "text" ? (
        <>
          <select
            value={docType}
            onChange={(e) => setDocType(e.target.value)}
            className="rounded border px-2 py-1 text-sm"
          >
            <option value="prose">prose</option>
            <option value="token">token</option>
          </select>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Document text…"
            required
            className="h-32 w-full rounded-md border px-3 py-2 text-sm focus:border-brand focus:outline-none"
          />
        </>
      ) : (
        <div className="space-y-2">
          <input
            type="file"
            accept={tab === "pptx" ? ".pptx" : ".py"}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            required
            className="text-sm"
          />
          {tab === "pptx" && (
            <>
              <div className="flex gap-4">
                <label className="text-xs text-gray-500">
                  Skip leading slides
                  <Input
                    type="number"
                    min={0}
                    value={skipLeading}
                    onChange={(e) => setSkipLeading(Math.max(0, Number(e.target.value) || 0))}
                    className="mt-1 w-24"
                  />
                </label>
                <label className="text-xs text-gray-500">
                  Skip trailing slides
                  <Input
                    type="number"
                    min={0}
                    value={skipTrailing}
                    onChange={(e) => setSkipTrailing(Math.max(0, Number(e.target.value) || 0))}
                    className="mt-1 w-24"
                  />
                </label>
              </div>
              <p className="text-xs text-gray-400">
                Drop cover / agenda / closing slides — they're discarded, not chunked.
              </p>
            </>
          )}
          {tab === "code" && (
            <>
              <Input
                placeholder="Topic (optional, e.g. file_io)"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
              />
              <p className="text-xs text-gray-400">
                Lecture is read from the W## filename and bound to the matching slides.
              </p>
            </>
          )}
        </div>
      )}
      {msg && <p className="text-sm text-gray-600">{msg}</p>}
      <Button type="submit" disabled={busy || (tab !== "text" && !file)}>
        {busy ? "Uploading…" : "Upload"}
      </Button>
    </form>
  );
}
