import type { DatasetPreview, Investigation, InvestigationSummary, Recommendation, Sample, Validation } from './types';

// Local default matches the Windows workflow (uvicorn on port 8000).
export const API_BASE: string = (
  import.meta.env.VITE_API_BASE ||
  import.meta.env.REACT_APP_BACKEND_URL ||
  'http://127.0.0.1:8000'
).replace(/\/$/, '');

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') throw err;
    throw new Error(`Could not reach the TraceRoot API at ${API_BASE}.`);
  }
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    throw new Error(
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg?: string }) => d.msg).join('; ')
          : `Request failed with status ${response.status}`
    );
  }
  return body as T;
}

const json = (method: string, data: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
});

const fileForm = (file: File, extra: Record<string, string> = {}) => {
  const form = new FormData();
  form.append('file', file);
  Object.entries(extra).forEach(([k, v]) => form.append(k, v));
  return form;
};

export const getHealth = () => request<{ status: string }>('/api/health');
export const getInvestigations = () =>
  request<{ count: number; investigations: InvestigationSummary[] }>('/api/investigations?workspace=local');
export const getInvestigation = (id: string) => request<Investigation>(`/api/investigations/${id}`);
export const deleteInvestigation = (id: string) => request<null>(`/api/investigations/${id}`, { method: 'DELETE' });
export const updateStatus = (id: string, status: string) =>
  request<Investigation>(`/api/investigations/${id}/status`, json('PATCH', { status }));
export const getSamples = () => request<{ samples: Sample[] }>('/api/samples');
export const sampleUrl = (name: string) => `${API_BASE}/api/samples/${encodeURIComponent(name)}`;
export const reportUrl = (id: string, autoprint = false) =>
  `${API_BASE}/api/investigations/${id}/report${autoprint ? '?autoprint=true' : ''}`;

export async function fetchSampleFile(name: string): Promise<File> {
  const response = await fetch(sampleUrl(name));
  if (!response.ok) throw new Error('Could not download the sample dataset.');
  return new File([await response.blob()], name, { type: 'text/csv' });
}

export const previewDataset = (file: File) =>
  request<DatasetPreview>('/api/datasets/preview', { method: 'POST', body: fileForm(file) });
export const analyzeDataset = (file: File) =>
  request<{ investigation: Investigation; created: boolean }>('/api/datasets/analyze', {
    method: 'POST',
    body: fileForm(file),
  });
export const validateFix = (id: string, file: File, description: string) =>
  request<{ validation: Validation['details']; investigation: Investigation }>(`/api/investigations/${id}/validations`, {
    method: 'POST',
    body: fileForm(file, { fix_description: description }),
  });
export const getPrevention = () => request<{ recommendations: Recommendation[] }>('/api/prevention?workspace=local');
export const setRecommendationStatus = (id: number, status: string) =>
  request<{ id: number; status: string }>(`/api/recommendations/${id}`, json('PATCH', { status }));

export const errorMessage = (err: unknown) => (err instanceof Error ? err.message : 'Unexpected error');

export const formatDate = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

export const fmt = (value: number | null | undefined) =>
  value == null ? '—' : Math.abs(value) >= 100 ? Math.round(value).toLocaleString() : String(Math.round(value * 10) / 10);
