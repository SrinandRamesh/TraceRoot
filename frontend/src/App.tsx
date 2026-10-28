import { useCallback, useEffect, useState } from 'react';
import './App.css';
import './features.css';
import { API_BASE, deleteInvestigation, errorMessage, formatDate, getHealth, getInvestigation, getInvestigations } from './api';
import type { Investigation, InvestigationSummary } from './types';
import { UploadPage } from './components/UploadPage';
import { InvestigationView } from './components/InvestigationView';
import { FixValidationPage } from './components/FixValidationPage';
import { PreventionPage } from './components/PreventionPage';

const POLL_MS = 15000;
const EMPTY = 'No investigations yet. Upload a dataset or connect a data source to begin.';
const SEVERITY_RANK: Record<string, number> = { Critical: 0, High: 1, Medium: 2, Low: 3, None: 4 };

type Page = 'Overview' | 'Investigations' | 'Analyze Data' | 'Investigation' | 'Fix Validation' | 'Prevention';

const NAV_GROUPS: { title: string; items: { label: Page; icon: string; description: string }[] }[] = [
  { title: 'MONITOR', items: [
    { label: 'Overview', icon: '▦', description: 'Summary of real investigations' },
    { label: 'Investigations', icon: '⌁', description: 'All analysed datasets' },
  ] },
  { title: 'INVESTIGATE', items: [
    { label: 'Analyze Data', icon: '⇪', description: 'Upload a CSV dataset' },
    { label: 'Investigation', icon: '✳', description: 'Problem, evidence and root cause' },
  ] },
  { title: 'RELIABILITY', items: [
    { label: 'Fix Validation', icon: '◇', description: 'Compare post-fix data' },
    { label: 'Prevention', icon: '⟳', description: 'Preventive actions from findings' },
  ] },
];

function App() {
  const [backendStatus, setBackendStatus] = useState('Connecting...');
  const [list, setList] = useState<InvestigationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState<Page>('Overview');
  const [selected, setSelected] = useState<Investigation | null>(null);
  const [search, setSearch] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [health, data] = await Promise.all([getHealth(), getInvestigations()]);
      setBackendStatus(health.status === 'healthy' ? 'Connected' : 'Unhealthy');
      setList(data.investigations);
      setError('');
    } catch (err) {
      setBackendStatus('Disconnected');
      setError(`${errorMessage(err)} Check that the backend is running.`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const navigate = (next: Page) => {
    setPage(next);
    window.scrollTo({ top: 0 });
  };

  const select = async (id: string, target: Page | null = 'Investigation') => {
    try {
      setSelected(await getInvestigation(id));
      if (target) navigate(target);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const updated = (inv: Investigation) => {
    setSelected(inv);
    void refresh();
  };

  const remove = async (id: string) => {
    try {
      await deleteInvestigation(id);
      setSelected(null);
      await refresh();
      navigate('Investigations');
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const problems = list.filter((i) => i.outcome !== 'no_significant_problem');
  const urgent = problems.filter((i) => ['Critical', 'High'].includes(i.severity));
  const unexplained = list.filter((i) => i.outcome === 'insufficient_evidence');
  const mostImportant = [...problems].filter((i) => i.status !== 'Resolved')
    .sort((a, b) => (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9))[0];
  const query = search.trim().toLowerCase();
  const filtered = query
    ? list.filter((i) => [i.id, i.title, i.dataset_name, i.severity, i.status, ...(i.affected_components ?? [])].some((v) => v.toLowerCase().includes(query)))
    : list;
  const refreshKey = list.map((i) => `${i.id}:${i.updated_at}`).join('|');
  const pad = (n: number) => String(n).padStart(2, '0');

  const rows = (items: InvestigationSummary[], compact = false) => {
    if (loading) return <div className="empty-state"><span className="loading-pulse" />Loading investigations…</div>;
    if (items.length === 0) {
      return (
        <div className="empty-state" data-testid="investigations-empty">
          <span className="empty-icon">⌁</span>
          <strong>{list.length ? 'No investigations match this search.' : EMPTY}</strong>
          {!list.length && <button className="primary-button" onClick={() => navigate('Analyze Data')} data-testid="empty-upload-button">Upload a dataset →</button>}
        </div>
      );
    }
    return (
      <div className={compact ? 'incident-list compact-list' : 'incident-list'}>
        {items.map((inv) => (
          <div className="incident-row" key={inv.id} data-testid={`investigation-row-${inv.id}`} role="button" tabIndex={0}
            onClick={() => void select(inv.id)} onKeyDown={(e) => e.key === 'Enter' && void select(inv.id)}>
            <div className={`incident-severity ${inv.severity.toLowerCase()}`} />
            <div className="incident-details">
              <strong>{inv.title}</strong>
              <span>{inv.id} · {inv.dataset_name} · {inv.source}{inv.affected_components?.length ? ` · ${inv.affected_components.join(', ')}` : ''} · {formatDate(inv.received_at)}</span>
            </div>
            <div className="incident-badges">
              <span className={`severity-label ${inv.severity.toLowerCase()}-text`} title={inv.severity_rationale}>{inv.severity === 'None' ? 'No issue' : inv.severity}</span>
              <span className={`incident-status status-${inv.status.toLowerCase().replace(/\s+/g, '-')}`}>{inv.status}</span>
            </div>
            <button className="text-button row-action" onClick={(e) => { e.stopPropagation(); void select(inv.id); }}>Open <span>↗</span></button>
          </div>
        ))}
      </div>
    );
  };

  const indicator = backendStatus === 'Connected' ? 'online' : backendStatus === 'Connecting...' ? '' : 'offline';

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand" onClick={() => navigate('Overview')} aria-label="TraceRoot AI home">
          <div className="brand-icon"><img src="/traceroot-logo.jpeg" alt="TraceRoot AI mascot" /><i /></div>
          <div className="brand-copy"><h1>TraceRoot <span>AI</span></h1><p>INCIDENT INTELLIGENCE</p></div>
        </button>

        <div className="workspace-block">
          <div className="sidebar-label">WORKSPACE</div>
          <div className="workspace-select-wrap"><span className="company-dot" /><span>Local uploads</span></div>
          <p className="workspace-caption">{list.length} investigation{list.length === 1 ? '' : 's'}</p>
        </div>

        <nav className="navigation" aria-label="Main navigation">
          {NAV_GROUPS.map((group) => (
            <div className="nav-group" key={group.title}>
              <div className="sidebar-label">{group.title}</div>
              {group.items.map((item) => (
                <button key={item.label} className={`nav-item ${page === item.label ? 'active' : ''}`} title={item.description}
                  onClick={() => navigate(item.label)} data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, '-')}`}>
                  <span className="nav-icon">{item.icon}</span>
                  <span className="nav-text">{item.label}</span>
                  {page === item.label && <span className="nav-active-mark" />}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className={`connection-indicator ${indicator}`} />
          <div className="connection-copy">
            <strong data-testid="backend-status">{backendStatus === 'Connected' ? 'Backend connected' : backendStatus === 'Connecting...' ? 'Connecting to API' : 'Backend unavailable'}</strong>
            <span>Dataset analysis · SQLite</span>
          </div>
          <span className={`demo-status ${backendStatus === 'Connected' ? 'online-text' : ''}`}>API</span>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <p className="breadcrumb">TraceRoot AI <span>/</span> {page}</p>
            <h2>{page === 'Overview' ? 'System overview' : page === 'Investigation' && selected ? selected.id : page}</h2>
          </div>
          <div className="topbar-actions">
            <span className="environment-badge"><span className="status-dot" />Local uploads<span className="badge-divider">/</span>dataset analysis</span>
            <div className="avatar">TR</div>
          </div>
        </header>

        {error && (
          <div className="error-banner" role="alert" data-testid="error-banner">
            <span>!</span><div>{error}</div>
            <button onClick={() => void refresh()}>Retry</button>
          </div>
        )}

        {page === 'Overview' && (
          <>
            <section className="welcome-section">
              <div className="hero-copy">
                <p className="eyebrow"><span className="eyebrow-line" />INCIDENT INTELLIGENCE PLATFORM</p>
                <h1>From signal to <span>root cause.</span></h1>
                <p className="welcome-description">Upload operational data, see what went wrong and where, verify the evidence, and turn the finding into a validated fix and prevention plan.</p>
                <div className="hero-actions">
                  <button className="primary-button" onClick={() => navigate('Analyze Data')} data-testid="hero-upload-button">Upload & investigate <span>→</span></button>
                  <span className="hero-status"><span className="status-dot" />{backendStatus === 'Connected' ? 'Connected to TraceRoot API' : backendStatus}</span>
                </div>
              </div>
              <div className="hero-visual" aria-hidden="true">
                <div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="orbit orbit-three" />
                <div className="hero-core"><span><img src="/traceroot-logo.jpeg" alt="" /></span><i>AI</i></div>
                <span className="orbit-node node-one">⌁</span><span className="orbit-node node-two">✳</span><span className="orbit-node node-three">◇</span>
                <div className="visual-caption">OBSERVE <b>·</b> CORRELATE <b>·</b> INVESTIGATE</div>
              </div>
            </section>

            <section className="stats-grid" data-testid="overview-stats">
              {[
                ['Investigations', list.length, 'Datasets analysed', 'blue', '⌁'],
                ['Problems identified', problems.length, 'Datasets with a detected problem', 'red', '!'],
                ['Critical or high', urgent.length, 'Based on error rate and latency impact', 'red', '↑'],
                ['Cause not established', unexplained.length, 'Need more corroborating data', 'purple', '?'],
              ].map(([label, value, note, color, icon]) => (
                <article className="stat-card" key={label as string}>
                  <div className="stat-top"><span>{label}</span><span className={`stat-icon ${color}`}>{icon}</span></div>
                  <h2>{loading ? '—' : pad(value as number)}</h2>
                  <p className="stat-note">{note}</p>
                </article>
              ))}
            </section>

            <section className="dashboard-grid">
              <article className="panel incident-panel">
                <div className="panel-heading">
                  <div><h3>Recent investigations</h3><p>Latest analysed datasets</p></div>
                  <button className="text-button" onClick={() => navigate('Investigations')}>View all <span>→</span></button>
                </div>
                {rows(list.slice(0, 4), true)}
              </article>
              <article className="panel assistant-panel tr-left" data-testid="most-important-finding">
                <p className="eyebrow">MOST IMPORTANT OPEN FINDING</p>
                {mostImportant ? (
                  <>
                    <h3>{mostImportant.severity} · {mostImportant.affected_components?.join(', ')}</h3>
                    <p>{mostImportant.problem_statement}</p>
                    <button className="primary-button" onClick={() => void select(mostImportant.id)}>Open investigation <span>→</span></button>
                  </>
                ) : (
                  <><h3>Nothing to review</h3><p>{list.length ? 'No open problems in the analysed datasets.' : EMPTY}</p></>
                )}
              </article>
            </section>
          </>
        )}

        {page === 'Investigations' && (
          <section className="panel page-panel">
            <div className="page-intro">
              <div>
                <p className="eyebrow">DATASET INVESTIGATIONS</p>
                <h3>Investigations</h3>
                <p>One record per analysed dataset; related anomalies are grouped into a single finding.</p>
              </div>
              <span className="count-pill" data-testid="investigation-count">{loading ? 'Loading…' : `${filtered.length} investigations`}</span>
            </div>
            <div className="incident-toolbar">
              <label className="search-box"><span>⌕</span>
                <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search problem, dataset, component…" data-testid="investigation-search-input" />
              </label>
              <button className="primary-button" onClick={() => navigate('Analyze Data')}>Upload dataset</button>
            </div>
            {rows(filtered)}
          </section>
        )}

        {page === 'Analyze Data' && <UploadPage onAnalyzed={(inv) => { updated(inv); navigate('Investigation'); }} />}

        {page === 'Investigation' && (selected ? (
          <InvestigationView inv={selected} onChange={updated} onDelete={(id) => void remove(id)} go={navigate} onOpen={(id) => void select(id)} />
        ) : (
          <section className="panel page-panel">
            <div className="page-intro"><div><p className="eyebrow">INVESTIGATION</p><h3>Select an investigation</h3><p>Open one to see the problem, evidence and likely cause.</p></div></div>
            {rows(list)}
          </section>
        ))}

        {page === 'Fix Validation' && (
          <FixValidationPage list={list} selected={selected} onSelect={(id) => void select(id, null)} onUpdated={updated} />
        )}

        {page === 'Prevention' && <PreventionPage refreshKey={refreshKey} onOpen={(id) => void select(id)} />}

        <footer className="footer">
          <span><strong>TraceRoot AI</strong><i>·</i>Evidence-backed incident investigation</span>
          <span>API {API_BASE.replace(/^https?:\/\//, '')}</span>
        </footer>
      </main>
    </div>
  );
}

export default App;
