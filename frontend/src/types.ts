export interface Hypothesis {
  hypothesis: string;
  score: number;
  assessment: 'supported' | 'weak' | 'tied';
  evidence: string[];
  contradicting: string[];
  services: string[];
  next_steps: string[];
  independent_signals: number;
}

export interface Anomaly {
  service: string;
  metric: string;
  label: string;
  start: string;
  end: string;
  count: number;
  peak: number;
  episode_median: number;
  baseline_median: number;
  baseline_upper: number;
  baseline_samples: number;
  ratio: number | null;
  reason: string;
}

export interface ErrorFinding {
  service: string;
  baseline_rate: number;
  later_rate: number;
  http_5xx: number;
  onset: string;
  errors_after_onset: number;
}

export interface ExceptionGroup {
  service: string;
  signature: string;
  count: number;
  with_5xx: number;
  first: string;
  last: string;
  sample: string;
}

export interface DataQuality {
  rows_received: number;
  rows_processed: number;
  duplicate_rows_removed: number;
  malformed_rows_padded_or_truncated: number;
  invalid_timestamps: number;
  out_of_order_timestamps: number;
  invalid_values_by_field: Record<string, number>;
  missing_values_by_column: Record<string, number>;
  column_mapping: Record<string, string>;
  ignored_columns: string[];
  service_name_variants_merged: Record<string, string[]>;
  normalization_notes: string[];
  fields_available: string[];
  limitations: string[];
}

export interface Problem {
  statement: string;
  affected_components: string[];
  onset: string;
  evidence: string[];
  likely_cause: string;
  certainty: string;
  next_step: string;
  missing_information: string[];
}

export interface AnalysisResult {
  status: 'problem_found' | 'insufficient_evidence' | 'no_significant_problem';
  problem: Problem | null;
  severity: string;
  severity_rationale: string;
  anomalies: Anomaly[];
  minor_deviations: Anomaly[];
  error_findings: ErrorFinding[];
  exceptions: ExceptionGroup[];
  change_events: { service: string; when: string; text: string }[];
  hypotheses: Hypothesis[];
  propagation: { label: string; order: { service: string; onset: string; latency_median: number; baseline_median: number }[] } | null;
  timeline: { when: string; kind: string; service: string; text: string }[];
  chart: { service: string; label: string; baseline_median: number; baseline_upper: number; points: { x: string | number; y: number; flag: boolean }[] } | null;
  limitations: string[];
  period: { start: string; end: string } | null;
  services: string[];
  method: string;
  data_quality: DataQuality;
}

export interface Recommendation {
  id: number;
  investigation_id: string;
  category: string;
  priority: string;
  problem: string;
  why: string;
  evidence: string;
  action: string;
  status: 'open' | 'in_progress' | 'completed';
  investigation_title?: string;
  dataset_name?: string;
}

export interface ValidationCheck {
  target: string;
  baseline_median: number;
  incident_median: number;
  post_median: number | null;
  samples: number;
  result: string;
  note: string;
}

export interface Validation {
  id: number;
  created_at: string;
  fix_description: string;
  dataset_name: string;
  result: string;
  details: { result: string; summary: string; checks: ValidationCheck[]; post_fix_new_anomalies: number; post_fix_problem: string | null };
}

export interface InvestigationSummary {
  id: string;
  workspace: string;
  title: string;
  dataset_name: string;
  source: string;
  status: string;
  outcome: AnalysisResult['status'];
  severity: string;
  severity_rationale?: string;
  primary_service: string | null;
  received_at: string;
  updated_at: string;
  problem_statement?: string | null;
  affected_components?: string[];
}

export interface Investigation extends InvestigationSummary {
  result: AnalysisResult;
  activity: { timestamp: string; kind: string; message: string }[];
  recommendations: Recommendation[];
  validations: Validation[];
  similar_past: {
    id: string;
    dataset_name: string;
    received_at: string;
    status: string;
    leading_cause: string;
    same_cause_family: boolean;
    shared_components: string[];
    confirmed_fix: string | null;
  }[];
}

export interface DatasetPreview {
  filename: string;
  row_count: number;
  columns: { name: string; mapped_to: string | null; detected_type: string; missing: number }[];
  ignored_columns: string[];
  sample_rows: Record<string, string>[];
}

export interface Sample {
  name: string;
  description: string;
}
