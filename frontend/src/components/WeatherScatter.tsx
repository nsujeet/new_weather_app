/**
 * WeatherScatter — canvas-based Tdb/Twb scatter via Chart.js.
 * Optional density mode: fetches a 2D histogram from the backend and renders
 * it as a colour-mapped matrix (chartjs-chart-matrix plugin).
 * Density is OFF by default — user opts in per chart session.
 */
import { useState } from "react";
import {
  Chart as ChartJS,
  LinearScale,
  PointElement,
  Tooltip,
  type ChartOptions,
} from "chart.js";
import { Scatter, Chart } from "react-chartjs-2";
import { MatrixController, MatrixElement } from "chartjs-chart-matrix";
import { getDensityData } from "../api";

ChartJS.register(LinearScale, PointElement, Tooltip, MatrixController, MatrixElement);

// sqrt-mapped viridis-like scale: dark blue → teal → yellow
function vColor(t: number): string {
  const r = Math.round(53  + t * 200);
  const g = Math.round(30  + t * 210);
  const b = Math.round(120 + t * -70);
  return `rgba(${r},${g},${b},0.92)`;
}

interface DensityResult {
  cells: { x: number; y: number; v: number }[];
  x_width: number;
  y_height: number;
  max_v: number;
}

interface Props {
  token: string;
  units: string;
  points: { x: number; y: number }[];
  refX?: number | null;
  refY?: number | null;
  accentColor?: string;
  sfx: string;
}

// Inline plugin that draws reference lines after the chart paints
function makeRefPlugin(refX: number | null | undefined, refY: number | null | undefined) {
  return {
    id: "refLines",
    afterDraw(chart: ChartJS) {
      const { ctx, chartArea, scales } = chart;
      if (!chartArea || !scales.x || !scales.y) return;
      ctx.save();
      ctx.strokeStyle = "#00B050";
      ctx.setLineDash([4, 3]);
      ctx.lineWidth = 1.2;
      if (refX != null) {
        const px = scales.x.getPixelForValue(refX);
        ctx.beginPath(); ctx.moveTo(px, chartArea.top); ctx.lineTo(px, chartArea.bottom); ctx.stroke();
      }
      if (refY != null) {
        const py = scales.y.getPixelForValue(refY);
        ctx.beginPath(); ctx.moveTo(chartArea.left, py); ctx.lineTo(chartArea.right, py); ctx.stroke();
      }
      ctx.restore();
    },
  };
}

const BASE_SCALES = (sfx: string) => ({
  x: {
    title: { display: true, text: `Dry bulb (${sfx})`, color: "#8b90a8", font: { size: 11 } },
    grid:  { color: "#2e3148" },
    ticks: { color: "#8b90a8", font: { size: 10 } },
  },
  y: {
    title: { display: true, text: `Wet bulb (${sfx})`, color: "#8b90a8", font: { size: 11 } },
    grid:  { color: "#2e3148" },
    ticks: { color: "#8b90a8", font: { size: 10 } },
  },
});

export default function WeatherScatter({
  token, units, points, refX, refY, accentColor = "#378ADD", sfx,
}: Props) {
  const [mode, setMode]       = useState<"scatter" | "density">("scatter");
  const [density, setDensity] = useState<DensityResult | null>(null);
  const [loading, setLoading] = useState(false);

  const refPlugin = makeRefPlugin(refX, refY);

  const switchDensity = async () => {
    if (density) { setMode("density"); return; }
    setLoading(true);
    try {
      const r = await getDensityData(token, units);
      setDensity(r);
      setMode("density");
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  // ── Scatter ────────────────────────────────────────────────────
  const scatterOpts: ChartOptions<"scatter"> = {
    animation: false,
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: (ctx) =>
            `Tdb ${ctx.parsed.x.toFixed(1)}${sfx}  Twb ${ctx.parsed.y.toFixed(1)}${sfx}`,
        },
      },
    },
    scales: BASE_SCALES(sfx),
  };

  const hexToRgba = (hex: string, a: number) => {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${a})`;
  };
  const dotColor = accentColor.startsWith("#")
    ? hexToRgba(accentColor, 0.18)
    : accentColor;

  // ── Density ────────────────────────────────────────────────────
  const densityDataset = density
    ? {
        type: "matrix" as const,
        data: density.cells.map((c) => ({ x: c.x, y: c.y, v: c.v })),
        backgroundColor(ctx: { dataIndex: number }) {
          const cell = density.cells[ctx.dataIndex];
          return cell ? vColor(Math.sqrt(cell.v / density.max_v)) : "transparent";
        },
        borderWidth: 0,
        width(ctx: { chart: ChartJS }) {
          const s = ctx.chart.scales.x;
          return s
            ? Math.max(1, Math.abs(s.getPixelForValue(density.x_width) - s.getPixelForValue(0)) - 0.5)
            : 4;
        },
        height(ctx: { chart: ChartJS }) {
          const s = ctx.chart.scales.y;
          return s
            ? Math.max(1, Math.abs(s.getPixelForValue(0) - s.getPixelForValue(density.y_height)) - 0.5)
            : 4;
        },
      }
    : null;

  const densityOpts = {
    animation: false,
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          label: (ctx: any) => {
            const d = density?.cells[ctx.dataIndex];
            return d ? `Tdb ≈${d.x.toFixed(1)}${sfx}  Twb ≈${d.y.toFixed(1)}${sfx}  n=${d.v}` : "";
          },
        },
      },
    },
    scales: {
      x: { ...BASE_SCALES(sfx).x, type: "linear" as const, offset: true },
      y: { ...BASE_SCALES(sfx).y, type: "linear" as const, offset: true },
    },
  };

  return (
    <div>
      {/* Toggle */}
      <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "8px" }}>
        {(["scatter", "density"] as const).map((m) => (
          <button
            key={m}
            onClick={() => m === "density" ? switchDensity() : setMode("scatter")}
            disabled={m === "density" && loading}
            style={{
              padding: "3px 12px", borderRadius: "6px", border: "none", outline: "none",
              background: mode === m ? "#1e2a4a" : "#16192a",
              color: mode === m ? "#a8c4ff" : "#8b90a8",
              fontSize: "11px", cursor: "pointer",
              fontWeight: mode === m ? 600 : 400,
            } as React.CSSProperties}
          >
            {m === "density" && loading ? "Loading…" : m === "scatter" ? "Scatter" : "Density"}
          </button>
        ))}
        {mode === "density" && (
          <span style={{ fontSize: "10px", color: "#6b7280" }}>
            yellow = most frequent · √(count) scale
          </span>
        )}
      </div>

      <div style={{ height: 280, position: "relative" }}>
        {mode === "scatter" && (
          <Scatter
            data={{
              datasets: [{
                data: points,
                pointRadius: 1.5,
                pointBackgroundColor: dotColor,
                pointBorderWidth: 0,
              }],
            }}
            options={scatterOpts}
            plugins={[refPlugin]}
          />
        )}
        {mode === "density" && densityDataset && (
          <Chart
            type="matrix"
            data={{ datasets: [densityDataset] }}
            // @ts-ignore — matrix options fully compatible at runtime
            options={densityOpts}
            plugins={[refPlugin]}
          />
        )}
      </div>
    </div>
  );
}
