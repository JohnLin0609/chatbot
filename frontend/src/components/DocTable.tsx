import type { DocumentMeta } from "../api/types";

export default function DocTable({
  docs,
  onToggle,
  onInspect,
  selected,
}: {
  docs: DocumentMeta[];
  onToggle: (d: DocumentMeta) => void;
  onInspect: (docId: string) => void;
  selected: string | null;
}) {
  if (!docs.length) {
    return <p className="text-sm text-gray-400">No documents yet.</p>;
  }
  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b text-left text-gray-500">
          <th className="py-2">Title</th>
          <th>Type</th>
          <th>Chunks</th>
          <th>Enabled</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {docs.map((d) => (
          <tr
            key={d.doc_id}
            className={`border-b ${selected === d.doc_id ? "bg-indigo-50" : ""}`}
          >
            <td className="py-2">{d.title || d.doc_id}</td>
            <td>{d.doc_type}</td>
            <td>{d.chunk_count}</td>
            <td>
              <button
                onClick={() => onToggle(d)}
                className={`rounded px-2 py-0.5 text-xs ${
                  d.enabled
                    ? "bg-green-100 text-green-700"
                    : "bg-gray-200 text-gray-500"
                }`}
              >
                {d.enabled ? "on" : "off"}
              </button>
            </td>
            <td className="text-right">
              <button
                onClick={() => onInspect(d.doc_id)}
                className="text-xs text-brand hover:underline"
              >
                inspect
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
