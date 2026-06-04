import { type FormEvent, useState } from "react";

import * as api from "../api/client";
import { Button, Input, errorMessage } from "./ui";

export default function UploadPanel({ onDone }: { onDone: () => void }) {
  const [tab, setTab] = useState<"text" | "pptx">("text");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [docType, setDocType] = useState("prose");
  const [file, setFile] = useState<File | null>(null);
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
          : await api.ingestPptx(file as File, title);
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

  const tabBtn = (key: "text" | "pptx", label: string) => (
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
        <input
          type="file"
          accept=".pptx"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          required
          className="text-sm"
        />
      )}
      {msg && <p className="text-sm text-gray-600">{msg}</p>}
      <Button type="submit" disabled={busy || (tab === "pptx" && !file)}>
        {busy ? "Uploading…" : "Upload"}
      </Button>
    </form>
  );
}
