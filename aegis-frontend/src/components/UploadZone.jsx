import { FileJson, FileSpreadsheet, Upload } from "lucide-react";
import { useState } from "react";
import { formatBytes } from "../lib/utils.js";

function buildPreview(file) {
  if (!file.name.match(/\.(csv|json)$/i)) return Promise.resolve([]);
  return file.text().then((text) => {
    if (file.name.endsWith(".json")) {
      const data = JSON.parse(text);
      const rows = Array.isArray(data) ? data : [data];
      return rows.slice(0, 5);
    }
    const [headerLine, ...lines] = text.split(/\r?\n/).filter(Boolean);
    const headers = headerLine.split(",");
    return lines.slice(0, 5).map((line) => Object.fromEntries(line.split(",").map((cell, index) => [headers[index] || `col_${index}`, cell])));
  }).catch(() => []);
}

export default function UploadZone({ onUpload }) {
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState([]);
  const handleFile = async (nextFile) => {
    if (!nextFile) return;
    setFile(nextFile);
    setPreview(await buildPreview(nextFile));
    onUpload?.(nextFile);
  };
  return (
    <div>
      <label onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); handleFile(event.dataTransfer.files?.[0]); }} className={`flex min-h-[260px] cursor-pointer flex-col items-center justify-center rounded-card border-2 border-dashed p-8 text-center transition ${dragging ? "border-aegis-blue bg-aegis-blue/10 shadow-glow" : "border-aegis-border bg-aegis-card/70 hover:border-aegis-blue"}`}>
        <Upload className="h-12 w-12 text-aegis-blue" />
        <p className="mt-4 text-xl font-bold text-white">Drop your dataset here</p>
        <p className="mt-2 text-sm text-aegis-muted">CSV, Excel, and JSON files are supported</p>
        <input type="file" accept=".csv,.xlsx,.xls,.json" className="hidden" onChange={(event) => handleFile(event.target.files?.[0])} />
      </label>
      {file ? (
        <div className="panel mt-5 p-5">
          <div className="flex items-center gap-3">
            {file.name.match(/\.json$/i) ? <FileJson className="h-5 w-5 text-aegis-purple" /> : <FileSpreadsheet className="h-5 w-5 text-aegis-green" />}
            <div><p className="font-semibold text-white">{file.name}</p><p className="text-sm text-aegis-muted">{formatBytes(file.size)}</p></div>
          </div>
          {preview.length ? (
            <div className="mt-4 overflow-auto rounded-button border border-aegis-border">
              <table className="w-full text-left text-sm">
                <thead className="bg-aegis-bg text-aegis-muted"><tr>{Object.keys(preview[0]).map((key) => <th key={key} className="px-3 py-2 font-medium">{key}</th>)}</tr></thead>
                <tbody>{preview.map((row, index) => <tr key={index} className="border-t border-aegis-border">{Object.keys(preview[0]).map((key) => <td key={key} className="px-3 py-2 text-aegis-text">{String(row[key])}</td>)}</tr>)}</tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
