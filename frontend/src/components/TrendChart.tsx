import type { AnalysisResult } from '../types';
import { fmt } from '../api';

export function TrendChart({ chart }: { chart: NonNullable<AnalysisResult['chart']> }) {
  const W = 760;
  const H = 180;
  const pad = 34;
  const ys = chart.points.map((p) => p.y).concat(chart.baseline_upper);
  const max = Math.max(...ys) * 1.05 || 1;
  const x = (i: number) => pad + (i / Math.max(1, chart.points.length - 1)) * (W - pad - 8);
  const y = (v: number) => H - 22 - (v / max) * (H - 34);
  const line = chart.points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`).join(' ');
  const label = (p: { x: string | number }) =>
    typeof p.x === 'number' ? `row ${p.x}` : new Date(p.x).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  return (
    <figure className="tr-chart" data-testid="trend-chart">
      <figcaption>
        {chart.label} · {chart.service} <span className="tr-muted">— dashed line: baseline alert level ({fmt(chart.baseline_upper)}), shaded points: flagged window</span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${chart.label} over time`}>
        <line x1={pad} x2={W - 8} y1={y(chart.baseline_upper)} y2={y(chart.baseline_upper)} className="tr-chart-threshold" />
        <line x1={pad} x2={W - 8} y1={y(chart.baseline_median)} y2={y(chart.baseline_median)} className="tr-chart-median" />
        <path d={line} className="tr-chart-line" />
        {chart.points.map((p, i) =>
          p.flag ? <circle key={i} cx={x(i)} cy={y(p.y)} r={2.6} className="tr-chart-flag" /> : null
        )}
        <text x={4} y={y(max / 1.05) + 4} className="tr-chart-axis">{fmt(max / 1.05)}</text>
        <text x={4} y={H - 22} className="tr-chart-axis">0</text>
        <text x={pad} y={H - 4} className="tr-chart-axis">{label(chart.points[0])}</text>
        <text x={W - 8} y={H - 4} textAnchor="end" className="tr-chart-axis">{label(chart.points[chart.points.length - 1])}</text>
      </svg>
    </figure>
  );
}
