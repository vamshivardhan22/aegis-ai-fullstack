import { FileSpreadsheet, Upload } from "lucide-react";
import { useState } from "react";
import { formatBytes } from "../lib/utils.js";

const MAX_BYTES = 10 * 1024 * 1024;

function parseCsvLine(line) {
  const cells = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"' && quoted && line[index + 1] === '"') {
      value += '"';
      index += 1;
    } else if (character === '"') {
      quoted = !quoted;
    } else if (character === "," && !quoted) {
      cells.push(value);
      value = "";
    } else {
      value += character;
    }
  }
  cells.push(value);
  return cells;
}

function buildPreview(file) {
  return file.text().then((text) => {
    const lines = text.split(/\r?\n/).filter((line) => line.trim().length);
    if (!lines.length) return [];
    const headers = parseCsvLine(lines[0]);
    return lines.slice(1, 6).map((line) => {
      const values = parseCsvLine(line);
      return Object.fromEntries(headers.map((header, index) => [header || `column_${index + 1}`, values[index] ?? ""]));
    });
  }).catch(() => []);
}

export default function UploadZone({ onUpload }) {
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState([]);
  const [error, setError] = useState("");

  const handleFile = async (nextFile) => {
    if (!nextFile) return;
    if (!/\.csv$/i.test(nextFile.name)) {
      setError("Only CSV files are supported by this workflow.");
      return;
    }
    if (nextFile.size > MAX_BYTES) {
      setError("The CSV exceeds the 10 MiB upload limit.");
      return;
    }
    if (nextFile.size === 0) {
      setError("The selected CSV is empty.");
      return;
    }
    setError("");
    setFile(nextFile);
    setPreview(await buildPreview(nextFile));
    onUpload?.(nextFile);
  };

  return (
    <div>
      <label
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => { event.preventDefault(); setDragging(false); handleFile(event.dataTransfer.files?.[0]); }}
        className={`flex min-h-[260px] cursor-pointer flex-col items-center justify-center rounded-card border-2 border-dashed p-8 text-center transition ${dragging ? "border-aegis-blue bg-aegis-blue/10 shadow-glow" : "border-aegis-border bg-aegis-card/70 hover:border-aegis-blue"}`}
      >
        <Upload className="h-12 w-12 text-aegis-blue" />
        <p className="mt-4 text-xl font-bold text-white">Drop your CSV here</p>
        <p className="mt-2 text-sm text-aegis-muted">CSV only · maximum 10 MiB</p>
        <input type="file" accept=".csv,text/csv" className="hidden" onChange={(event) => handleFile(event.target.files?.[0])} />
      </label>
      {error ? <p role="alert" className="mt-3 text-sm text-aegis-red">{error}</p> : null}
      {file ? (
        <div className="panel mt-5 p-5">
          <div className="flex items-center gap-3">
            <FileSpreadsheet className="h-5 w-5 text-aegis-green" />
            <div><p className="font-semibold text-white">{file.name}</p><p className="text-sm text-aegis-muted">{formatBytes(file.size)}</p></div>
          </div>
          {preview.length ? (
            <div className="mt-4 overflow-auto rounded-button border border-aegis-border">
              <table className="w-full text-left text-sm">
                <thead className="bg-aegis-bg text-aegis-muted"><tr>{Object.keys(preview[0]).map((key) => <th key={key} className="px-3 py-2 font-medium">{key}</th>)}</tr></thead>
                <tbody>{preview.map((row, index) => <tr key={index} className="border-t border-aegis-border">{Object.keys(preview[0]).map((key) => <td key={key} className="px-3 py-2 text-aegis-text">{String(row[key])}</td>)}</tr>)}</tbody>
              </table>
            </div>
          ) : <p className="mt-4 text-sm text-aegis-muted">No preview rows are available.</p>}
        </div>
      ) : null}
    </div>
  );
}
