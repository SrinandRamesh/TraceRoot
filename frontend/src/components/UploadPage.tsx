import { useEffect, useRef, useState } from 'react';
import { analyzeDataset, errorMessage, fetchSampleFile, getSamples, previewDataset, sampleUrl } from '../api';
import type { DatasetPreview, Investigation, Sample } from '../types';

export function UploadPage({ onAnalyzed }: { onAnalyzed: (inv: Investigation) => void }) {
  const [samples, setSamples] = useState<Sample[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [busy, setBusy] = useState<'' | 'preview' | 'analyze'>('');
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getSamples().then((r) => setSamples(r.samples)).catch(() => setSamples([]));
  }, []);

  const choose = async (next: File) => {
    setFile(next);
    setPreview(null);
    setError('');
    if (!next.name.toLowerCase().endsWith('.csv')) {
      setError('Please choose a .csv file.');
      return;
    }
    setBusy('preview');
    try {
      setPreview(await previewDataset(next));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy('');
    }
  };

  const analyze = async () => {
    if (!file) return;
    setBusy('analyze');
    setError('');
    try {
      onAnalyzed((await analyzeDataset(file)).investigation);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy('');
    }
  };

  return (
    <section className="panel page-panel tr-left" data-testid="upload-page">
      <div className="page-intro">
        <div>
          <p className="eyebrow">DATASET ANALYSIS</p>
          <h3>Upload & investigate</h3>
          <p>Upload a CSV of metrics or logs. TraceRoot cleans it, compares each signal with its own baseline, and reports the problem, the evidence and the most likely cause.</p>
        </div>
      </div>

      <div className="tr-two-col">
        <div className="tr-stack">
          <div
            className={`tr-drop ${dragging ? 'is-dragging' : ''}`}
            data-testid="upload-dropzone"
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              if (e.dataTransfer.files[0]) void choose(e.dataTransfer.files[0]);
            }}
            onClick={() => input.current?.click()}
          >
            <strong>Drop a CSV file here or click to browse</strong>
            <span className="tr-muted tr-small">Max 10 MB · timestamps, services, latency, errors, status codes, resource metrics or log messages</span>
            <input ref={input} type="file" accept=".csv,text/csv" hidden data-testid="upload-file-input"
              onChange={(e) => e.target.files?.[0] && void choose(e.target.files[0])} />
          </div>

          {file && (
            <div className="tr-card" data-testid="selected-file">
              <div className="tr-row-between">
                <div>
                  <strong>{file.name}</strong>
                  <span className="tr-muted tr-small"> · {(file.size / 1024).toFixed(1)} KB{preview ? ` · ${preview.row_count} rows · ${preview.columns.length} columns` : ''}</span>
                </div>
                <button className="primary-button" disabled={!preview || busy !== ''} onClick={() => void analyze()} data-testid="analyze-button">
                  {busy === 'analyze' ? 'Analyzing…' : 'Analyze dataset'}
                </button>
              </div>
              {busy === 'preview' && <p className="tr-muted">Reading file…</p>}
              {preview && <PreviewTable preview={preview} />}
            </div>
          )}
          {error && <div className="tr-alert tr-alert-error" data-testid="upload-error">{error}</div>}
        </div>

        <div className="tr-card" data-testid="sample-datasets">
          <h4>Sample datasets</h4>
          <p className="tr-muted tr-small">Synthetic files generated for this demo (not real company data). They go through exactly the same pipeline as any upload.</p>
          <ul className="tr-list">
            {samples.map((s) => (
              <li key={s.name}>
                <strong>{s.name}</strong>
                <span className="tr-small tr-muted">{s.description}</span>
                <span className="tr-inline-actions">
                  <button className="tr-id-link" data-testid={`use-sample-${s.name}`}
                    onClick={async () => { try { await choose(await fetchSampleFile(s.name)); } catch (err) { setError(errorMessage(err)); } }}>
                    Load for analysis
                  </button>
                  <a className="tr-id-link" href={sampleUrl(s.name)} download data-testid={`download-sample-${s.name}`}>Download</a>
                </span>
              </li>
            ))}
            {samples.length === 0 && <li className="tr-muted tr-small">Samples unavailable (backend not reachable).</li>}
          </ul>
        </div>
      </div>
    </section>
  );
}

function PreviewTable({ preview }: { preview: DatasetPreview }) {
  const headers = preview.columns.map((c) => c.name);
  const usable = preview.columns.some((c) => c.mapped_to && !['timestamp', 'service', 'event_type'].includes(c.mapped_to));
  return (
    <div className="tr-gap-top" data-testid="dataset-preview">
      {!usable && (
        <div className="tr-alert tr-alert-warn" data-testid="preview-warning">
          No telemetry columns were recognized (latency, errors, status codes, resource metrics or log messages). Analysis will fail unless columns are renamed — see the README for supported names.
        </div>
      )}
      <div className="tr-chip-row">
        {preview.columns.map((c) => (
          <span key={c.name} className={`tr-col-chip ${c.mapped_to ? '' : 'is-ignored'}`} title={`${c.detected_type}, ${c.missing} missing`}>
            {c.name} → {c.mapped_to ?? 'ignored'} <i>{c.detected_type}{c.missing ? ` · ${c.missing} missing` : ''}</i>
          </span>
        ))}
      </div>
      <div className="tr-table-wrap">
        <table className="tr-table">
          <thead><tr>{headers.map((h) => <th key={h}>{h}</th>)}</tr></thead>
          <tbody>
            {preview.sample_rows.map((row, i) => (
              <tr key={i}>{headers.map((h) => <td key={h}>{row[h]}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="tr-muted tr-small">First {preview.sample_rows.length} raw rows, before cleaning.</p>
    </div>
  );
}
