import { useState } from 'react';
import { errorMessage, fmt, formatDate, reportUrl, updateStatus } from '../api';
import type { Investigation } from '../types';
import { TrendChart } from './TrendChart';

const STATUSES = ['Open', 'Investigating', 'Monitoring', 'Resolved'];
const OUTCOME_TITLE = {
  problem_found: 'Problem identified',
  insufficient_evidence: 'Problem identified · root cause not established',
  no_significant_problem: 'No significant problem detected',
};

type Props = {
  inv: Investigation;
  onChange: (inv: Investigation) => void;
  onDelete: (id: string) => void;
  go: (page: 'Fix Validation' | 'Prevention') => void;
  onOpen: (id: string) => void;
};

export function InvestigationView({ inv, onChange, onDelete, go, onOpen }: Props) {
  const r = inv.result;
  const p = r.problem;
  const q = r.data_quality;
  const [error, setError] = useState('');
  const top = r.hypotheses[0];

  const changeStatus = async (status: string) => {
    setError('');
    try {
      onChange(await updateStatus(inv.id, status));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <section className="panel page-panel tr-left" data-testid="investigation-view">
      <div className="tr-row-between">
        <div>
          <p className="eyebrow">DATASET INVESTIGATION · {inv.id}</p>
          <p className="tr-muted tr-small" data-testid="investigation-source">
            {inv.dataset_name} · {inv.source} · analysed {formatDate(inv.received_at)} · {q.rows_processed} rows · {r.services.length} component(s)
          </p>
        </div>
        <div className="tr-inline-actions">
          {inv.outcome !== 'no_significant_problem' && (
            <select value={inv.status} data-testid="investigation-status-select" onChange={(e) => void changeStatus(e.target.value)}>
              {STATUSES.map((s) => <option key={s}>{s}</option>)}
            </select>
          )}
          <a className="secondary-button" href={reportUrl(inv.id, true)} target="_blank" rel="noreferrer" data-testid="export-report-link">Export report (PDF)</a>
          <button className="tr-id-link tr-danger" data-testid="delete-investigation-button"
            onClick={() => window.confirm(`Delete ${inv.id}?`) && onDelete(inv.id)}>Delete</button>
        </div>
      </div>
      {error && <div className="tr-alert tr-alert-error" data-testid="status-error">{error}</div>}

      <div className={`tr-problem tr-outcome-${inv.outcome}`} data-testid="problem-card">
        <span className="tr-problem-label">{OUTCOME_TITLE[inv.outcome]}</span>
        <p className="tr-problem-statement" data-testid="problem-statement">
          {p ? p.statement : 'No sustained deviation, error-rate increase or repeated exception was found in this dataset. No incident was created.'}
        </p>
        <div className="tr-facts">
          <div><span>Affected</span><strong data-testid="affected-components">{p?.affected_components.join(', ') || '—'}</strong></div>
          <div><span>Started</span><strong>{p?.onset ?? '—'}</strong></div>
          <div><span>Severity</span><strong className={`severity-text-${r.severity.toLowerCase()}`} data-testid="severity">{r.severity}</strong></div>
          <div><span>Status</span><strong>{inv.status}</strong></div>
        </div>
        <p className="tr-small tr-muted">Severity basis: {r.severity_rationale}</p>
      </div>

      {p && (
        <div className="tr-two-col tr-gap-top">
          <div className="tr-stack">
            <div className="tr-card">
              <h4>Likely root cause</h4>
              <p data-testid="likely-cause"><strong>{p.likely_cause}</strong></p>
              <p className="tr-small tr-muted">Certainty — {p.certainty}</p>
            </div>
            <div className="tr-card tr-next" data-testid="next-step">
              <h4>Recommended next action</h4>
              <p><strong>{p.next_step}</strong></p>
              {top && top.next_steps.length > 1 && <ul className="tr-plain">{top.next_steps.slice(1).map((s) => <li key={s}>{s}</li>)}</ul>}
              <p className="tr-small tr-muted">TraceRoot does not change any system. Actions marked "needs human approval" are proposals only.</p>
              <div className="tr-inline-actions">
                <button className="tr-id-link" onClick={() => go('Fix Validation')} data-testid="goto-fix-validation">Validate a fix with post-fix data →</button>
                <button className="tr-id-link" onClick={() => go('Prevention')} data-testid="goto-prevention">{inv.recommendations.length} preventive recommendation(s) →</button>
              </div>
            </div>
          </div>
          <div className="tr-card" data-testid="evidence-list">
            <h4>Evidence (observed in the data)</h4>
            <ul className="tr-plain">{p.evidence.map((e) => <li key={e}>{e}</li>)}</ul>
            {[...p.missing_information, ...r.limitations].length > 0 && (
              <>
                <h4 className="tr-gap-top">Limitations & missing information</h4>
                <ul className="tr-plain tr-muted">{[...p.missing_information, ...r.limitations].map((e) => <li key={e}>{e}</li>)}</ul>
              </>
            )}
          </div>
        </div>
      )}

      {p && inv.similar_past.length > 0 && (
        <div className="tr-card tr-gap-top" data-testid="pattern-memory">
          <h4>Seen before</h4>
          <ul className="tr-list">
            {inv.similar_past.slice(0, 3).map((m) => (
              <li key={m.id} data-testid={`similar-${m.id}`}>
                <span className="tr-inline-actions">
                  <button className="tr-id-link" onClick={() => onOpen(m.id)}>{m.id}</button>
                  <span className="tr-small tr-muted">{formatDate(m.received_at)}</span>
                </span>
                <span className="tr-small">Cause then: <b>{m.leading_cause}</b></span>
                {m.confirmed_fix && <span className="tr-small">Fix that worked: <b>{m.confirmed_fix}</b></span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {r.chart && <div className="tr-card tr-gap-top"><TrendChart chart={r.chart} /></div>}

      {r.hypotheses.length > 0 && (
        <div className="tr-card tr-gap-top" data-testid="hypotheses">
          <h4>Ranked hypotheses <span className="tr-muted tr-small">— explained rule points, not probabilities; correlation is not proof</span></h4>
          {r.hypotheses.map((h, i) => (
            <details key={h.hypothesis} className="tr-hyp" open={i === 0}>
              <summary>
                <span className="rank-number">{String(i + 1).padStart(2, '0')}</span>
                <strong>{h.hypothesis}</strong>
                <span className={`tr-tag tr-tag-${h.assessment}`}>{h.assessment}</span>
                <b>{h.score} pts</b>
              </summary>
              <ul className="tr-plain">{h.evidence.map((e) => <li key={e}>{e}</li>)}</ul>
              {h.contradicting.length > 0 && <ul className="tr-plain tr-muted">{h.contradicting.map((e) => <li key={e}>Caveat: {e}</li>)}</ul>}
            </details>
          ))}
        </div>
      )}

      {(r.anomalies.length > 0 || r.error_findings.length > 0 || r.exceptions.length > 0) && (
        <div className="tr-card tr-gap-top" data-testid="anomaly-table">
          <h4>Detected anomalies vs. dataset baseline</h4>
          <div className="tr-table-wrap">
            <table className="tr-table">
              <thead><tr><th>Component</th><th>Signal</th><th>Window</th><th>Baseline</th><th>During</th><th>Peak</th><th>Why flagged</th></tr></thead>
              <tbody>
                {r.anomalies.map((a) => (
                  <tr key={`${a.service}-${a.metric}-${a.start}`}><td>{a.service}</td><td>{a.label}</td><td>{a.start} → {a.end}</td>
                    <td>{fmt(a.baseline_median)}</td><td>{fmt(a.episode_median)}</td><td>{fmt(a.peak)}</td><td className="tr-small">{a.reason}</td></tr>
                ))}
                {r.error_findings.map((e) => (
                  <tr key={`err-${e.service}`}><td>{e.service}</td><td>error rate</td><td>from {e.onset}</td>
                    <td>{(e.baseline_rate * 100).toFixed(0)}%</td><td>{(e.later_rate * 100).toFixed(0)}%</td><td>{e.http_5xx} × 5xx</td>
                    <td className="tr-small">Rate after onset ≥ 2× baseline and +5 points</td></tr>
                ))}
                {r.exceptions.map((g) => (
                  <tr key={`exc-${g.service}-${g.signature}`}><td>{g.service}</td><td>repeated error</td><td>{g.first} → {g.last}</td>
                    <td>—</td><td>{g.count} times</td><td>{g.with_5xx} × 5xx</td><td className="tr-small" title={g.sample}>{g.signature}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="tr-two-col tr-gap-top">
        <div className="tr-card" data-testid="timeline">
          <h4>Timeline</h4>
          {r.propagation && (
            <div className="tr-assessment" data-testid="propagation">
              <strong>Onset order: </strong>{r.propagation.order.map((o) => `${o.service} (${o.onset})`).join(' → ')}
              <div className="tr-small tr-muted">{r.propagation.label}.</div>
            </div>
          )}
          <ul className="tr-activity">
            {r.timeline.map((t, i) => (
              <li key={i}><span className="tr-muted">{t.when}</span><span className="tr-activity-kind">{t.kind}</span><span>{t.service && <b>{t.service}: </b>}{t.text}</span></li>
            ))}
          </ul>
        </div>
        <div className="tr-card" data-testid="data-quality">
          <h4>Data quality</h4>
          <div className="tr-metric-row">
            <span>Received <b>{q.rows_received}</b></span><span>Processed <b>{q.rows_processed}</b></span>
            <span>Duplicates removed <b>{q.duplicate_rows_removed}</b></span><span>Invalid timestamps <b>{q.invalid_timestamps}</b></span>
            <span>Out of order <b>{q.out_of_order_timestamps}</b></span>
          </div>
          <ul className="tr-plain tr-small">
            <li>Columns used: {Object.entries(q.column_mapping).map(([k, v]) => `${k} → ${v}`).join(', ')}</li>
            {q.ignored_columns.length > 0 && <li>Ignored columns: {q.ignored_columns.join(', ')}</li>}
            {Object.keys(q.missing_values_by_column).length > 0 && <li>Missing cells: {Object.entries(q.missing_values_by_column).map(([k, v]) => `${k} ${v}`).join(', ')} (not filled in)</li>}
            {Object.keys(q.invalid_values_by_field).length > 0 && <li>Invalid values excluded: {Object.entries(q.invalid_values_by_field).map(([k, v]) => `${k} ${v}`).join(', ')}</li>}
            {Object.entries(q.service_name_variants_merged).map(([k, v]) => <li key={k}>Merged names {v.join(' / ')} → {k}</li>)}
            {q.normalization_notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
          <h4 className="tr-gap-top">Activity</h4>
          <ul className="tr-plain tr-small">{inv.activity.map((a, i) => <li key={i}>{formatDate(a.timestamp)} — {a.message}</li>)}</ul>
          <p className="tr-small tr-muted">Method: {r.method}</p>
        </div>
      </div>
    </section>
  );
}
