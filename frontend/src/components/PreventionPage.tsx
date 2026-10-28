import { useEffect, useState } from 'react';
import { errorMessage, getPrevention, setRecommendationStatus } from '../api';
import type { Recommendation } from '../types';

const PRIORITY = { High: 0, Medium: 1, Low: 2 } as Record<string, number>;

export function PreventionPage({ refreshKey, onOpen }: { refreshKey: string; onOpen: (id: string) => void }) {
  const [recs, setRecs] = useState<Recommendation[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    getPrevention().then((r) => { setRecs(r.recommendations); setError(''); }).catch((err) => setError(errorMessage(err)));
  }, [refreshKey]);

  const update = async (rec: Recommendation, status: Recommendation['status']) => {
    try {
      await setRecommendationStatus(rec.id, status);
      setRecs((current) => current?.map((r) => (r.id === rec.id ? { ...r, status } : r)) ?? null);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const sorted = [...(recs ?? [])].sort((a, b) => (PRIORITY[a.priority] ?? 3) - (PRIORITY[b.priority] ?? 3));
  const done = (recs ?? []).filter((r) => r.status === 'completed').length;

  return (
    <section className="panel page-panel tr-left" data-testid="prevention-page">
      <div className="page-intro">
        <div>
          <p className="eyebrow">RELIABILITY WORKFLOW</p>
          <h3>Prevention center</h3>
          <p>Preventive actions generated from the findings of each investigation. Every item links back to the evidence that motivated it.</p>
        </div>
        {recs && recs.length > 0 && <span className="count-pill">{done}/{recs.length} completed</span>}
      </div>
      {error && <div className="tr-alert tr-alert-error">{error}</div>}
      {!recs && !error && <div className="empty-state"><span className="loading-pulse" />Loading…</div>}
      {recs && recs.length === 0 && (
        <div className="empty-state" data-testid="prevention-empty">
          <strong>No preventive recommendations yet</strong>
          <span>They appear after an analysed dataset identifies a problem.</span>
        </div>
      )}
      {sorted.length > 0 && (
        <div className="tr-table-wrap">
          <table className="tr-table" data-testid="prevention-table">
            <thead><tr><th>Priority</th><th>Category</th><th>Recommended action</th><th>Addresses / evidence</th><th>Investigation</th><th>Status</th></tr></thead>
            <tbody>
              {sorted.map((r) => (
                <tr key={r.id} className={r.status === 'completed' ? 'is-done' : ''}>
                  <td><span className={`tr-tag tr-priority-${r.priority.toLowerCase()}`}>{r.priority}</span></td>
                  <td>{r.category}</td>
                  <td><strong>{r.action}</strong></td>
                  <td className="tr-small">{r.problem}<br /><span className="tr-muted">{r.evidence}. {r.why}</span></td>
                  <td><button className="tr-id-link" onClick={() => onOpen(r.investigation_id)}>{r.investigation_id}</button><br /><span className="tr-small tr-muted">{r.dataset_name}</span></td>
                  <td>
                    <select value={r.status} data-testid={`rec-status-${r.id}`} onChange={(e) => void update(r, e.target.value as Recommendation['status'])}>
                      <option value="open">Open</option><option value="in_progress">In progress</option><option value="completed">Completed</option>
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
