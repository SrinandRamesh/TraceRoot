import { useState } from 'react';
import { errorMessage, fmt, formatDate, validateFix } from '../api';
import type { Investigation, InvestigationSummary, Validation } from '../types';

const LABEL: Record<string, string> = {
  improved: 'Improved', worsened: 'Worsened', inconclusive: 'Inconclusive', insufficient_data: 'Insufficient data',
  partially_improved: 'Partially improved', not_measured: 'Not measured',
};

type Props = {
  list: InvestigationSummary[];
  selected: Investigation | null;
  onSelect: (id: string) => void;
  onUpdated: (inv: Investigation) => void;
};

export function FixValidationPage({ list, selected, onSelect, onUpdated }: Props) {
  const candidates = list.filter((i) => i.outcome !== 'no_significant_problem');
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [latest, setLatest] = useState<Validation['details'] | null>(null);
  const inv = selected && selected.outcome !== 'no_significant_problem' ? selected : null;

  const submit = async () => {
    if (!inv || !file) return;
    setBusy(true);
    setError('');
    try {
      const response = await validateFix(inv.id, file, description);
      setLatest(response.validation);
      onUpdated(response.investigation);
    } catch (err) {
      setLatest(null);
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel page-panel tr-left" data-testid="fix-validation-page">
      <div className="page-intro">
        <div>
          <p className="eyebrow">RELIABILITY WORKFLOW</p>
          <h3>Fix validation</h3>
          <p>Upload data collected after a fix. TraceRoot compares the same signals with the original baseline and incident period. It never applies fixes itself, and only a measured return to baseline counts as improved.</p>
        </div>
      </div>

      {candidates.length === 0 ? (
        <div className="empty-state" data-testid="fix-validation-empty">
          <strong>No investigations with a detected problem yet</strong>
          <span>Analyze a dataset first; findings to validate will appear here.</span>
        </div>
      ) : (
        <div className="tr-two-col">
          <div className="tr-card tr-stack">
            <label className="tr-field">Investigation
              <select data-testid="validation-investigation-select" value={inv?.id ?? ''} onChange={(e) => { onSelect(e.target.value); setLatest(null); }}>
                <option value="" disabled>Select an investigation…</option>
                {candidates.map((i) => <option key={i.id} value={i.id}>{i.id} · {i.dataset_name} · {i.severity} · {i.affected_components?.join(', ')}</option>)}
              </select>
            </label>
            {inv && (
              <div className="tr-small">
                <strong>Targets to re-check:</strong>
                <ul className="tr-plain">
                  {inv.result.anomalies.map((a) => <li key={a.service + a.metric + a.start}>{a.service} {a.label}: baseline {fmt(a.baseline_median)}, during incident {fmt(a.episode_median)}</li>)}
                  {inv.result.error_findings.map((e) => <li key={e.service}>{e.service} error rate: baseline {(e.baseline_rate * 100).toFixed(0)}%, during incident {(e.later_rate * 100).toFixed(0)}%</li>)}
                  {inv.result.anomalies.length + inv.result.error_findings.length === 0 && <li>Only log patterns were found; upload post-fix logs to compare error rates.</li>}
                </ul>
              </div>
            )}
            <label className="tr-field">Fix being validated
              <input data-testid="validation-description-input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. Raised DB pool from 20 to 40 in staging" />
            </label>
            <label className="tr-field">Post-fix dataset (CSV, same kind of columns)
              <input type="file" accept=".csv" data-testid="validation-file-input" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </label>
            <button className="primary-button" disabled={!inv || !file || description.trim().length < 3 || busy} onClick={() => void submit()} data-testid="validation-submit-button">
              {busy ? 'Comparing…' : 'Compare with original findings'}
            </button>
            {error && <div className="tr-alert tr-alert-error" data-testid="validation-error">{error}</div>}
          </div>

          <div className="tr-stack">
            {latest && <ValidationResult v={latest} />}
            <div className="tr-card" data-testid="validation-history">
              <h4>Validation history</h4>
              {inv?.validations.length ? (
                <ul className="tr-list">
                  {inv.validations.map((v) => (
                    <li key={v.id}>
                      <span className={`tr-tag tr-tag-${v.result}`}>{LABEL[v.result] ?? v.result}</span>
                      <strong>{v.fix_description}</strong>
                      <span className="tr-small tr-muted">{v.dataset_name} · {formatDate(v.created_at)}</span>
                      <span className="tr-small">{v.details.summary}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="tr-muted">No validations recorded for this investigation.</p>}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function ValidationResult({ v }: { v: Validation['details'] }) {
  return (
    <div className={`tr-card tr-result tr-result-${v.result}`} data-testid="validation-result">
      <p className="eyebrow">RESULT</p>
      <h4 data-testid="validation-result-label">{LABEL[v.result]}</h4>
      <p>{v.summary}</p>
      <div className="tr-table-wrap">
        <table className="tr-table">
          <thead><tr><th>Target</th><th>Baseline</th><th>Incident</th><th>Post-fix</th><th>Result</th></tr></thead>
          <tbody>
            {v.checks.map((c) => (
              <tr key={c.target}><td>{c.target}</td><td>{fmt(c.baseline_median)}</td><td>{fmt(c.incident_median)}</td>
                <td>{fmt(c.post_median)}</td><td><span className={`tr-tag tr-tag-${c.result}`}>{LABEL[c.result]}</span> <span className="tr-small tr-muted">{c.note}</span></td></tr>
            ))}
          </tbody>
        </table>
      </div>
      {v.post_fix_problem && <p className="tr-small tr-muted">The post-fix data also contains its own deviation: {v.post_fix_problem}</p>}
    </div>
  );
}
