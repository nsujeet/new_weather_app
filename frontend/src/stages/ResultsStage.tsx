/**
 * ResultsStage — full design conditions: ACF selector, comparison table,
 * percentile table, yearly summary, winterization, OM section, psychro chart.
 */
import { useState, useEffect } from "react";
import { useStore } from "../store";
import { getPsychroChart, getScatterData, getHeatmapData, getFreezingData, downloadResults } from "../api";
import type { OmStat, AshraConditionResult } from "../api";
import Card from "../components/Card";
import WeatherScatter from "../components/WeatherScatter";
import {
  XAxis, YAxis, Tooltip as RCTooltip,
  CartesianGrid, ResponsiveContainer, BarChart, Bar,
} from "recharts";

// ── ACF config ────────────────────────────────────────────────────

const ACF_OPTIONS = [
  { label: "0.4%  (99.6th)", acf: 99.6, pct: 0.4 },
  { label: "1%    (99th)",   acf: 99,   pct: 1   },
  { label: "2%    (98th)",   acf: 98,   pct: 2   },
  { label: "5%    (95th)",   acf: 95,   pct: 5   },
] as const;

// ── small helpers ─────────────────────────────────────────────────

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between py-1.5 border-b border-gray-100 last:border-0 text-sm">
      <span className="text-gray-500">{label}</span>
      <span className="font-medium text-gray-800">{value}</span>
    </div>
  );
}

function MetricBox({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ background: "var(--wa-surface-2)", borderRadius: "8px", padding: "12px", textAlign: "center" }}>
      <p style={{ fontSize: "11px", color: "var(--wa-text-dim)", marginBottom: "4px" }}>{label}</p>
      <p style={{ fontSize: "18px", fontWeight: 700, color: "var(--wa-text)" }}>{value}</p>
    </div>
  );
}

// ── row lookup from Stats array ───────────────────────────────────

type StatsRow = Record<string, unknown>;

function getRowVal(stats: StatsRow[], col: string, pct: number): number | null {
  if (!stats?.length) return null;
  // exact match first
  let row = stats.find((r) => Number(r["%"]) === pct);
  if (!row) {
    // closest
    row = stats.reduce((best, r) =>
      Math.abs(Number(r["%"]) - pct) < Math.abs(Number(best["%"]) - pct) ? r : best
    );
  }
  const v = row?.[col];
  return v != null && !Number.isNaN(Number(v)) ? Number(v) : null;
}

function fmt1(v: number | null, suffix = ""): string {
  return v != null ? `${v.toFixed(1)}${suffix}` : "—";
}

// ── OM stat lookup ────────────────────────────────────────────────

function getOmVal(stats: OmStat[], col: keyof OmStat, pct: number): number | null {
  if (!stats?.length) return null;
  let row = stats.find((r) => Number(r["%"]) === pct);
  if (!row) {
    row = stats.reduce((best, r) =>
      Math.abs(Number(r["%"]) - pct) < Math.abs(Number(best["%"]) - pct) ? r : best
    );
  }
  const v = row?.[col];
  return v != null ? Number(v) : null;
}

// ── ASHRAE detail table (collapsible) ────────────────────────────

function AshraDetailCard({ ashraConditions, levelKey, sfx, units }: {
  ashraConditions: AshraConditionResult[];
  levelKey: "0.4" | "1" | "2";
  sfx: string;
  units: "F" | "C";
}) {
  const [show, setShow] = useState(false);
  const pUnit = units === "C" ? "kPa" : "psia";
  return (
    <Card title={`ASHRAE Nearby Stations — ${ashraConditions.length} fetched`}>
      <button onClick={() => setShow((v) => !v)} className="text-sm text-blue-600 hover:underline mb-2">
        {show ? "▲ Hide" : "▼ Show"} all ASHRAE stations
      </button>
      {show && (
        <div className="overflow-x-auto">
          <table className="text-xs w-full">
            <thead>
              <tr className="border-b border-gray-200">
                {["Station", "WMO", `${levelKey}% Tdb (${sfx})`, `${levelKey}% Twb (${sfx})`, `MCWB (${sfx})`, `MCDB (${sfx})`, `Pressure (${pUnit})`].map((h) => (
                  <th key={h} className="py-1 px-2 text-left text-gray-500 font-medium whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ashraConditions.map((a, i) => {
                const lv = a.levels?.[levelKey];
                const p = a.pressure_psia;
                const pDisplay = p != null
                  ? (units === "C" ? (p * 6.8948).toFixed(3) : p.toFixed(3))
                  : "—";
                return (
                  <tr key={a.wmo} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="py-0.5 px-2 font-medium">{i === 0 ? "★ " : ""}{a.station ?? a.wmo}</td>
                    <td className="py-0.5 px-2 font-mono">{a.wmo}</td>
                    <td className="py-0.5 px-2 font-mono text-right">{lv?.tdb  != null ? lv.tdb.toFixed(1)  : "—"}</td>
                    <td className="py-0.5 px-2 font-mono text-right">{lv?.twb  != null ? lv.twb.toFixed(1)  : "—"}</td>
                    <td className="py-0.5 px-2 font-mono text-right">{lv?.mcwb != null ? lv.mcwb.toFixed(1) : "—"}</td>
                    <td className="py-0.5 px-2 font-mono text-right">{lv?.mcdb != null ? lv.mcdb.toFixed(1) : "—"}</td>
                    <td className="py-0.5 px-2 font-mono text-right">{pDisplay}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────

export default function ResultsStage() {
  const { processResult, omResult, omLoading, omError, ashraConditions, units, setStage } = useStore();
  const [acfIdx,       setAcfIdx]       = useState(1);
  const [chartSrc,     setChartSrc]     = useState<string | null>(null);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError,   setChartError]   = useState<string | null>(null);
  const [scatterPts,   setScatterPts]   = useState<{x:number;y:number}[]|null>(null);
  const [heatCells,    setHeatCells]    = useState<{month:string;year:number;value:number}[]|null>(null);
  const [freezeBars,   setFreezeBars]   = useState<{week:number;hours:number}[]|null>(null);
  const [showPct,      setShowPct]      = useState(false);
  const [showYearly,   setShowYearly]   = useState(false);
  const [showOm,       setShowOm]       = useState(false);

  // OM chart state
  const [omScatterPts,    setOmScatterPts]    = useState<{x:number;y:number}[]|null>(null);
  const [omHeatCells,     setOmHeatCells]     = useState<{month:string;year:number;value:number}[]|null>(null);
  const [omFreezeBars,    setOmFreezeBars]    = useState<{week:number;hours:number}[]|null>(null);
  const [omChartSrc,      setOmChartSrc]      = useState<string | null>(null);
  const [omChartLoading,  setOmChartLoading]  = useState(false);

  // Auto-load NOAA charts whenever the process token changes (includes first mount
  // and navigation back to this stage after re-processing).
  useEffect(() => {
    const t = processResult?.result_token;
    if (!t) return;
    setScatterPts(null); setFreezeBars(null); setHeatCells(null);
    getScatterData(t, units).then((r) => setScatterPts(r.points)).catch(() => setScatterPts([]));
    getFreezingData(t).then((r) => setFreezeBars(r.bars)).catch(() => setFreezeBars([]));
    getHeatmapData(t, units).then((r) => setHeatCells(r.cells)).catch(() => setHeatCells([]));
  }, [processResult?.result_token]);

  // Auto-load OM charts and auto-expand section once the OM token is available.
  useEffect(() => {
    const omT = omResult?.om_token;
    if (!omT) return;
    setShowOm(true);
    setOmScatterPts(null); setOmFreezeBars(null); setOmHeatCells(null);
    getScatterData(omT, units).then((r) => setOmScatterPts(r.points)).catch(() => setOmScatterPts([]));
    getFreezingData(omT).then((r) => setOmFreezeBars(r.bars)).catch(() => setOmFreezeBars([]));
    getHeatmapData(omT, units).then((r) => setOmHeatCells(r.cells)).catch(() => setOmHeatCells([]));
  }, [omResult?.om_token]);

  if (!processResult) return null;

  const { meta, design_conditions, psychro_qa } = processResult;
  const dc   = design_conditions as Record<string, unknown>;
  const stats = (dc?.Stats ?? []) as StatsRow[];
  const qaMetrics = (dc?.qa as Record<string, unknown>)?.metrics as Record<string, unknown> | undefined;
  const yearlyRows = (dc?.yearly_grouping ?? []) as Record<string, unknown>[];

  const sfx  = units === "C" ? "°C" : "°F";
  const pUnit = units === "C" ? "kPa" : "psia";
  const dbCol  = units === "C" ? "DB_C"   : "DB_F";
  const wbCol  = units === "C" ? "WB_C"   : "WB_F";
  const mwbCol = units === "C" ? "MCWB_C" : "MCWB_F";
  const mdbCol = units === "C" ? "MCDB_C" : "MCDB_F";

  const selAcf = ACF_OPTIONS[acfIdx];
  const pct    = selAcf.pct; // e.g. 1

  // NOAA values at selected ACF
  const nTdb  = getRowVal(stats, dbCol,  pct);
  const nTwb  = getRowVal(stats, wbCol,  pct);
  const nMcwb = getRowVal(stats, mwbCol, pct);
  const nMcdb = getRowVal(stats, mdbCol, pct);
  const maxDegHrsYear = qaMetrics?.max_degF_hrs_year as number | undefined;
  const totalKdegHrs  = qaMetrics?.total_kdegF_hrs   as number | undefined;

  // OM values at selected ACF
  const omStats = omResult?.stats ?? [];
  const omDbCol  = units === "C" ? "DB_C"   : "DB_F";
  const omWbCol  = units === "C" ? "WB_C"   : "WB_F";
  const omMwbCol = units === "C" ? "MCWB_C" : "MCWB_F";
  const omMdbCol = units === "C" ? "MCDB_C" : "MCDB_F";
  const omTdb  = getOmVal(omStats, omDbCol  as keyof OmStat, pct);
  const omTwb  = getOmVal(omStats, omWbCol  as keyof OmStat, pct);
  const omMcwb = getOmVal(omStats, omMwbCol as keyof OmStat, pct);
  const omMcdb = getOmVal(omStats, omMdbCol as keyof OmStat, pct);

  // ASHRAE: pick level key, grab up to 3 valid stations
  const ashraLevelKey = pct <= 0.4 ? "0.4" : pct <= 1 ? "1" : "2";
  type LvKey = "0.4" | "1" | "2";
  const ashraValid = ashraConditions.filter((c) => c.levels?.[ashraLevelKey as LvKey]);
  const hasAshrae = ashraValid.length > 0;
  const ashraShow = ashraValid.slice(0, 3); // max 3 columns

  // pressure display
  const pressureDisplay = units === "C"
    ? `${(meta.pressure_psi * 6.8948).toFixed(3)} ${pUnit}`
    : `${meta.pressure_psi.toFixed(3)} ${pUnit}`;

  // all columns in Stats for the percentile table
  const colsShow = ["%", dbCol, mwbCol, wbCol, mdbCol].filter(
    (c) => stats.length > 0 && c in stats[0]
  );

  const token = processResult.result_token;

  // Derive actual data window label from heatmap cells (both NOAA and OM)
  const dataWindowLabel = (cells: typeof heatCells) => {
    if (!cells || cells.length === 0) return null;
    const years = [...new Set(cells.map((c) => c.year))].sort();
    return years.length > 1 ? `${years[0]}–${years[years.length - 1]}` : String(years[0]);
  };

  const loadChart = async () => {
    setChartLoading(true); setChartError(null);
    try {
      const r = await getPsychroChart(token, units);
      setChartSrc(`data:image/png;base64,${r.image_b64}`);
    } catch (e: unknown) {
      setChartError(e instanceof Error ? e.message : "Chart failed");
    } finally { setChartLoading(false); }
  };

  const omToken = omResult?.om_token;
  const loadOmChart = async () => {
    if (!omToken) return;
    setOmChartLoading(true);
    try {
      const r = await getPsychroChart(omToken, units);
      setOmChartSrc(`data:image/png;base64,${r.image_b64}`);
    } catch { /* ignore */ }
    finally { setOmChartLoading(false); }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <button onClick={() => setStage("filter")} className="text-xs text-blue-600 hover:underline">
          ← Change filter / re-process
        </button>
        <button
          onClick={() => downloadResults(token, meta.station_id)}
          className="text-xs px-3 py-1 rounded border border-[#2e3148] text-[#8b90a8] hover:border-[#4f8ef7] hover:text-[#4f8ef7] transition-colors bg-transparent"
        >
          ⬇ Download results CSV
        </button>
      </div>

      {/* ── OM status banner (visible while ERA5 is loading or errored) ── */}
      {!omResult && omLoading && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs" style={{ background: "#0a2a20", border: "1px solid #1a5040", color: "#34d399" }}>
          <span className="animate-spin inline-block w-3 h-3 border-2 border-emerald-400 border-t-transparent rounded-full" />
          Open-Meteo ERA5 fetching in background — comparison column will appear when done…
        </div>
      )}
      {!omResult && omError && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs" style={{ background: "#2a1a0a", border: "1px solid #5a3010", color: "#fb923c" }}>
          <span>⚠</span>
          Open-Meteo ERA5 unavailable — {omError}
        </div>
      )}

      {/* ── ACF selector ──────────────────────────────────────── */}
      <Card title="Annual cumulative frequency">
        <div className="flex flex-wrap gap-2">
          {ACF_OPTIONS.map((opt, i) => (
            <button
              key={opt.label}
              onClick={() => setAcfIdx(i)}
              className={`px-3 py-1.5 rounded-full border text-sm font-medium transition-colors ${
                i === acfIdx
                  ? "bg-[#4f8ef7] text-white border-[#4f8ef7]"
                  : "bg-[#1a1d27] text-[#8b90a8] border-[#2e3148] hover:border-[#4f8ef7]"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </Card>

      {/* ── NOAA key metrics ───────────────────────────────────── */}
      <Card title={`NOAA Design Conditions — ${pct}% exceedance`}>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          <MetricBox label={`${pct}% Tdb`}      value={fmt1(nTdb, sfx)} />
          <MetricBox label={`${pct}% Twb`}      value={fmt1(nTwb, sfx)} />
          <MetricBox label="MCWB @ Tdb"          value={fmt1(nMcwb, sfx)} />
          <MetricBox label="MCDB @ Twb"          value={fmt1(nMcdb, sfx)} />
        </div>
        {(maxDegHrsYear != null || totalKdegHrs != null) && (
          <div className="grid grid-cols-2 gap-3 mb-4">
            {maxDegHrsYear != null && (
              <MetricBox label="Max deg-hrs year" value={String(maxDegHrsYear)} />
            )}
            {totalKdegHrs != null && (
              <MetricBox
                label={`Total k${sfx}-hrs (10yr)`}
                value={`${(units === "C" ? totalKdegHrs * 5 / 9 : totalKdegHrs).toFixed(1)}`}
              />
            )}
          </div>
        )}

        {/* Comparison table NOAA vs ASHRAE#1..N vs OM */}
        {(omResult || hasAshrae) && (
          <div className="overflow-x-auto">
            <table className="text-xs w-full">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-1.5 pr-4 text-gray-500 font-semibold">Metric</th>
                  <th className="text-right py-1.5 pr-4 text-blue-700 font-semibold">NOAA</th>
                  {ashraShow.map((a, i) => (
                    <th key={a.wmo} className="text-right py-1.5 pr-4 text-purple-700 font-semibold whitespace-nowrap">
                      {i === 0 ? "★ " : ""}ASHRAE #{i + 1}
                      {a.ashrae_version && (
                        <span className="text-gray-400 font-normal"> ({a.ashrae_version})</span>
                      )}
                    </th>
                  ))}
                  {omResult && <th className="text-right py-1.5 text-emerald-700 font-semibold">Open-Meteo</th>}
                  {!omResult && omLoading && <th className="text-right py-1.5 text-emerald-600 font-semibold animate-pulse">OM…</th>}
                  {!omResult && omError && <th className="text-right py-1.5 text-orange-500 font-semibold">OM ✕</th>}
                </tr>
              </thead>
              <tbody>
                {[
                  { label: `${pct}% Tdb (${sfx})`, noaa: nTdb,  key: "tdb"  as const },
                  { label: `${pct}% Twb (${sfx})`, noaa: nTwb,  key: "twb"  as const },
                  { label: `MCWB @ Tdb (${sfx})`,  noaa: nMcwb, key: "mcwb" as const },
                  { label: `MCDB @ Twb (${sfx})`,  noaa: nMcdb, key: "mcdb" as const },
                ].map((row) => (
                  <tr key={row.label} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="py-1 pr-4 text-gray-600">{row.label}</td>
                    <td className="py-1 pr-4 text-right font-mono text-blue-700">{fmt1(row.noaa)}</td>
                    {ashraShow.map((a) => (
                      <td key={a.wmo} className="py-1 pr-4 text-right font-mono text-purple-700">
                        {fmt1(a.levels?.[ashraLevelKey as LvKey]?.[row.key] ?? null)}
                      </td>
                    ))}
                    {omResult && (
                      <td className="py-1 text-right font-mono text-emerald-700">
                        {fmt1(row.key === "tdb" ? omTdb : row.key === "twb" ? omTwb : row.key === "mcwb" ? omMcwb : omMcdb)}
                      </td>
                    )}
                    {!omResult && omLoading && <td className="py-1 text-right text-emerald-600 text-xs animate-pulse">…</td>}
                    {!omResult && omError && <td className="py-1 text-right text-orange-500 text-xs">—</td>}
                  </tr>
                ))}
                <tr className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-1 pr-4 text-gray-600">Pressure ({pUnit})</td>
                  <td className="py-1 pr-4 text-right font-mono text-blue-700">{pressureDisplay}</td>
                  {ashraShow.map((a) => (
                    <td key={a.wmo} className="py-1 pr-4 text-right font-mono text-purple-700">
                      {a.pressure_psia != null
                        ? `${(units === "C" ? a.pressure_psia * 6.8948 : a.pressure_psia).toFixed(3)}`
                        : "—"}
                    </td>
                  ))}
                  {omResult && <td className="py-1 text-right font-mono text-emerald-700">—</td>}
                  {!omResult && omLoading && <td className="py-1 text-right text-emerald-600 text-xs animate-pulse">…</td>}
                  {!omResult && omError && <td className="py-1 text-right text-orange-500 text-xs">—</td>}
                </tr>
                <tr className="hover:bg-gray-50">
                  <td className="py-1 pr-4 text-gray-600">Station</td>
                  <td className="py-1 pr-4 text-right font-mono text-blue-700 text-xs">{meta.station_id}</td>
                  {ashraShow.map((a) => (
                    <td key={a.wmo} className="py-1 pr-4 text-right font-mono text-purple-700 text-xs">
                      {a.station ?? a.wmo}
                    </td>
                  ))}
                  {omResult && <td className="py-1 text-right font-mono text-emerald-700 text-xs">ERA5</td>}
                  {!omResult && omLoading && <td className="py-1 text-right text-emerald-600 text-xs animate-pulse">fetching ERA5…</td>}
                  {!omResult && omError && <td className="py-1 text-right text-orange-500 text-xs" title={omError ?? ""}>ERA5 ✕</td>}
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* ── ASHRAE all stations detail (collapsible) ─────────── */}
      {ashraConditions.length > 0 && (
        <AshraDetailCard
          ashraConditions={ashraConditions}
          levelKey={ashraLevelKey as LvKey}
          sfx={sfx}
          units={units}
        />
      )}

      {/* ── Processing QA waterfall ──────────────────────────── */}
      {processResult.processing_qa && (() => {
        const pqa = processResult.processing_qa!;
        const m = pqa.metrics;
        const steps = [
          { label: "Raw merged",    rows: m.rows_original },
          { label: "Resampled",     rows: m.rows_resample },
          { label: "Donor-filled",  rows: m.rows_replacement },
          { label: "Interpolated",  rows: m.rows_interpolated },
          { label: "Winterization", rows: m.rows_winterization },
        ];
        return (
          <Card title="Processing QA">
            <div className="grid grid-cols-5 gap-2 mb-3">
              {steps.map((s, i) => (
                <div key={s.label} className="text-center">
                  <p className="text-xs text-gray-500 mb-0.5">{i + 1}. {s.label}</p>
                  <p className="text-sm font-semibold text-gray-800">{s.rows.toLocaleString()}</p>
                  {i > 0 && (
                    <p className="text-xs text-gray-400">
                      {steps[i - 1].rows > 0 ? `–${(steps[i - 1].rows - s.rows).toLocaleString()}` : ""}
                    </p>
                  )}
                </div>
              ))}
            </div>
            <div className="grid grid-cols-3 gap-2 mb-2">
              <div className="bg-gray-50 rounded p-2 text-center">
                <p className="text-xs text-gray-500">TMP_F filled</p>
                <p className="text-sm font-semibold">{m.filled_TMP_F.toLocaleString()}</p>
              </div>
              <div className="bg-gray-50 rounded p-2 text-center">
                <p className="text-xs text-gray-500">DEW_F filled</p>
                <p className="text-sm font-semibold">{m.filled_DEW_F.toLocaleString()}</p>
              </div>
              <div className={`rounded p-2 text-center ${m.remaining_nan > 0 ? "bg-yellow-50" : "bg-gray-50"}`}>
                <p className="text-xs text-gray-500">Remaining NaN</p>
                <p className="text-sm font-semibold">{m.remaining_nan.toLocaleString()}</p>
              </div>
            </div>
            <p className="text-xs text-gray-400">
              10yr window: {m.window_10y} · 15yr window: {m.window_15y} · Avg missing: {m.avg_missing_pct}%
            </p>
            {pqa.messages.length > 0 && (
              <ul className="text-xs text-amber-700 mt-2 space-y-0.5">
                {pqa.messages.map((msg, i) => <li key={i}>⚠ {msg}</li>)}
              </ul>
            )}
          </Card>
        );
      })()}

      {/* ── Station metadata ──────────────────────────────────── */}
      <Card title="Station & Site">
        <MetaRow label="Station" value={`${meta.station_name} (${meta.station_id})`} />
        <MetaRow label="Distance" value={`${meta.distance_miles.toFixed(1)} mi`} />
        <MetaRow label="Elev delta" value={`${meta.elevation_delta_ft.toFixed(0)} ft`} />
        <MetaRow label="Pressure" value={pressureDisplay} />
        <MetaRow
          label="Timezone"
          value={`${meta.timezone} (UTC${meta.delta_time >= 0 ? "+" : ""}${meta.delta_time}h)`}
        />
        <MetaRow label="Rows used" value={processResult.n_rows.toLocaleString()} />
        <MetaRow label="Filter" value={processResult.filter_used} />
      </Card>

      {/* ── QA warnings ──────────────────────────────────────── */}
      {psychro_qa.messages.length > 0 && (
        <Card title="QA Warnings">
          <ul className="text-sm text-amber-700 space-y-1">
            {psychro_qa.messages.map((m, i) => (
              <li key={i} className="flex gap-2"><span>⚠</span><span>{m}</span></li>
            ))}
          </ul>
        </Card>
      )}

      {/* ── Winterization banners ────────────────────────────── */}
      {processResult.winterization?.no_freeze_start && (
        <div style={{ background: "#1a2a1a", border: "1px solid #2a5a2a", borderRadius: "8px", padding: "10px 14px", fontSize: "13px", color: "#66dd66" }}>
          <span style={{ fontWeight: 600 }}>No-freeze window (NOAA 15yr): </span>
          {processResult.winterization.no_freeze_start} → {processResult.winterization.no_freeze_end}
        </div>
      )}
      {omResult?.winterization?.no_freeze_start && (
        <div style={{ background: "#1a2a24", border: "1px solid #2a5a44", borderRadius: "8px", padding: "10px 14px", fontSize: "13px", color: "#34d399" }}>
          <span style={{ fontWeight: 600 }}>No-freeze window (OM 15yr): </span>
          {omResult.winterization.no_freeze_start} → {omResult.winterization.no_freeze_end}
        </div>
      )}

      {/* ── NOAA Charts ──────────────────────────────────────── */}
      <Card title="NOAA — Charts">
        {/* Scatter */}
        <div className="mb-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Weather scatter — Tdb vs Twb</p>
          {!scatterPts
            ? <span className="text-xs text-gray-400 animate-pulse">Loading…</span>
            : <WeatherScatter token={token} units={units} points={scatterPts} refX={nTdb} refY={nTwb} sfx={sfx} />
          }
        </div>

        {/* Freezing bar */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Freezing hours per ISO week{dataWindowLabel(heatCells) ? ` (${dataWindowLabel(heatCells)})` : ""}
            </p>
            {!freezeBars && <span className="text-xs text-gray-400 animate-pulse">Loading…</span>}
          </div>
          {freezeBars && freezeBars.length > 0 && (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={freezeBars} margin={{ top: 5, right: 10, bottom: 20, left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="week" label={{ value: "Fiscal week", position: "insideBottom", offset: -10 }} tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <RCTooltip formatter={(v: number) => [`${v} hrs`, "Hours below 36°F"]} />
                <Bar dataKey="hours" fill="#378ADD" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Min temp heatmap */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Min temperature heatmap{dataWindowLabel(heatCells) ? ` (${dataWindowLabel(heatCells)})` : ""}
            </p>
            {!heatCells && <span className="text-xs text-gray-400 animate-pulse">Loading…</span>}
          </div>
          {heatCells && heatCells.length > 0 && (() => {
            const years = [...new Set(heatCells.map((c) => c.year))].sort();
            const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
            const lookup: Record<string, number> = {};
            heatCells.forEach((c) => { lookup[`${c.month}-${c.year}`] = c.value; });
            const minV = Math.min(...heatCells.map((c) => c.value));
            const maxV = Math.max(...heatCells.map((c) => c.value));
            const colour = (v: number) => {
              const t = (v - minV) / (maxV - minV || 1);
              const r = Math.round(220 - t * 170);
              const g = Math.round(50 + t * 170);
              return `rgb(${r},${g},50)`;
            };
            return (
              <div className="overflow-x-auto">
                <table className="text-xs border-collapse">
                  <thead>
                    <tr>
                      <th className="px-1 py-0.5 text-gray-500 text-left">Month</th>
                      {years.map((y) => <th key={y} className="px-1 py-0.5 text-gray-500 text-center">{y}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {months.map((m) => (
                      <tr key={m}>
                        <td className="px-1 py-0.5 font-medium text-gray-600">{m}</td>
                        {years.map((y) => {
                          const v = lookup[`${m}-${y}`];
                          return (
                            <td key={y} className="px-1 py-0.5 text-center font-mono"
                              style={v != null ? { backgroundColor: colour(v), color: "#fff", borderRadius: 2 } : {}}>
                              {v != null ? v.toFixed(1) : ""}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })()}
        </div>
      </Card>

      {/* ── Open-Meteo Charts ────────────────────────────────── */}
      {omResult && omToken && (
        <Card title="Open-Meteo ERA5 — Charts">
          {/* Scatter */}
          <div className="mb-4">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Weather scatter — Tdb vs Twb</p>
            {!omScatterPts
              ? <span className="text-xs text-gray-400 animate-pulse">Loading…</span>
              : <WeatherScatter token={omToken!} units={units} points={omScatterPts} refX={omTdb} refY={omTwb} accentColor="#10b981" sfx={sfx} />
            }
          </div>

          {/* Freezing bar */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                Freezing hours per ISO week{dataWindowLabel(omHeatCells) ? ` (${dataWindowLabel(omHeatCells)})` : ""}
              </p>
              {!omFreezeBars && <span className="text-xs text-gray-400 animate-pulse">Loading…</span>}
            </div>
            {omFreezeBars && omFreezeBars.length > 0 && (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={omFreezeBars} margin={{ top: 5, right: 10, bottom: 20, left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="week" label={{ value: "Fiscal week", position: "insideBottom", offset: -10 }} tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <RCTooltip formatter={(v: number) => [`${v} hrs`, "Hours below 36°F"]} />
                  <Bar dataKey="hours" fill="#10b981" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Heatmap */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                Min temperature heatmap{dataWindowLabel(omHeatCells) ? ` (${dataWindowLabel(omHeatCells)})` : ""}
              </p>
              {!omHeatCells && <span className="text-xs text-gray-400 animate-pulse">Loading…</span>}
            </div>
            {omHeatCells && omHeatCells.length > 0 && (() => {
              const years = [...new Set(omHeatCells.map((c) => c.year))].sort();
              const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
              const lookup: Record<string, number> = {};
              omHeatCells.forEach((c) => { lookup[`${c.month}-${c.year}`] = c.value; });
              const minV = Math.min(...omHeatCells.map((c) => c.value));
              const maxV = Math.max(...omHeatCells.map((c) => c.value));
              const colour = (v: number) => {
                const t = (v - minV) / (maxV - minV || 1);
                const r = Math.round(220 - t * 170);
                const g = Math.round(50 + t * 170);
                return `rgb(${r},${g},50)`;
              };
              return (
                <div className="overflow-x-auto">
                  <table className="text-xs border-collapse">
                    <thead>
                      <tr>
                        <th className="px-1 py-0.5 text-gray-500 text-left">Month</th>
                        {years.map((y) => <th key={y} className="px-1 py-0.5 text-gray-500 text-center">{y}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {months.map((m) => (
                        <tr key={m}>
                          <td className="px-1 py-0.5 font-medium text-gray-600">{m}</td>
                          {years.map((y) => {
                            const v = lookup[`${m}-${y}`];
                            return (
                              <td key={y} className="px-1 py-0.5 text-center font-mono"
                                style={v != null ? { backgroundColor: colour(v), color: "#fff", borderRadius: 2 } : {}}>
                                {v != null ? v.toFixed(1) : ""}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            })()}
          </div>

          {/* Psychro chart */}
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Psychrometric chart</p>
            {!omChartSrc && (
              <button onClick={loadOmChart} disabled={omChartLoading}
                className="w-full bg-gray-100 hover:bg-gray-200 disabled:opacity-50 text-gray-700 font-medium py-2 px-4 rounded-lg text-sm transition-colors">
                {omChartLoading ? "Rendering…" : "▶ Generate OM Psychrometric Chart"}
              </button>
            )}
            {omChartSrc && (
              <>
                <img src={omChartSrc} alt="OM Psychrometric chart" className="w-full rounded-lg mt-2" />
                <button onClick={() => setOmChartSrc(null)} className="mt-2 text-xs text-gray-400 hover:text-gray-600">
                  ✕ Clear
                </button>
              </>
            )}
          </div>
        </Card>
      )}

      {/* ── Full percentile table (collapsible) ──────────────── */}
      {stats.length > 0 && (
        <Card title="Percentile Table">
          <button
            onClick={() => setShowPct((v) => !v)}
            className="text-sm text-blue-600 hover:underline mb-2"
          >
            {showPct ? "▲ Hide" : "▼ Show"} full table — NOAA
          </button>
          {showPct && (
            <div className="overflow-x-auto">
              <table className="text-xs w-full">
                <thead>
                  <tr className="border-b border-gray-200">
                    {colsShow.map((c) => (
                      <th key={c} className="text-right py-1 px-2 text-gray-500 font-medium first:text-left">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {stats.map((row, i) => {
                    const rowPct = Number(row["%"]);
                    const isHighlighted = rowPct === pct;
                    return (
                      <tr
                        key={i}
                        style={isHighlighted ? { background: "#1e2a4a", color: "#a8c4ff" } : {}}
                        className={`border-b ${isHighlighted ? "border-[#4f8ef7] font-semibold" : "border-gray-100 hover:bg-gray-50"}`}
                      >
                        {colsShow.map((c) => (
                          <td key={c} className="py-0.5 px-2 font-mono text-right first:text-left">
                            {c === "%" ? String(row[c] ?? "") : Number(row[c]).toFixed(1)}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Yearly summary */}
          {yearlyRows.length > 0 && (
            <div className="mt-3">
              <button
                onClick={() => setShowYearly((v) => !v)}
                className="text-sm text-blue-600 hover:underline mb-2"
              >
                {showYearly ? "▲ Hide" : "▼ Show"} yearly summary — NOAA
              </button>
              {showYearly && (
                <div className="overflow-x-auto">
                  <table className="text-xs w-full">
                    <thead>
                      <tr className="border-b border-gray-200">
                        {Object.keys(yearlyRows[0]).map((k) => (
                          <th key={k} className="text-right py-1 px-2 text-gray-500 font-medium first:text-left">
                            {k}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {yearlyRows.map((row, i) => (
                        <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                          {Object.values(row).map((v, j) => (
                            <td key={j} className="py-0.5 px-2 font-mono text-right first:text-left">
                              {typeof v === "number" ? v.toFixed(1) : String(v)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </Card>
      )}

      {/* ── Open-Meteo quick estimate (collapsible) ──────────── */}
      {omResult && (
        <Card title="Open-Meteo ERA5 — Quick Estimate">
          <button
            onClick={() => setShowOm((v) => !v)}
            className="text-sm text-blue-600 hover:underline mb-2"
          >
            {showOm ? "▲ Collapse" : "▼ Expand"} OM percentile table
          </button>
          {showOm && omResult.stats.length > 0 && (
            <div className="overflow-x-auto">
              <table className="text-xs w-full">
                <thead>
                  <tr className="border-b border-gray-200">
                    {["%" , `DB_${units}`, `WB_${units}`, `MCWB_${units}`, `MCDB_${units}`].map((c) => (
                      <th key={c} className="text-right py-1 px-2 text-gray-500 font-medium first:text-left">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {omResult.stats.map((row, i) => {
                    const rowPct = Number(row["%"]);
                    const isHighlighted = rowPct === pct;
                    return (
                      <tr
                        key={i}
                        style={isHighlighted ? { background: "#0f2a20", color: "#6ee7b7" } : {}}
                        className={`border-b ${isHighlighted ? "border-emerald-700 font-semibold" : "border-gray-100 hover:bg-gray-50"}`}
                      >
                        <td className="py-0.5 px-2 font-mono">{row["%"]}</td>
                        <td className="py-0.5 px-2 font-mono text-right">
                          {fmt1(getOmVal(omResult.stats, omDbCol as keyof OmStat, rowPct))}
                        </td>
                        <td className="py-0.5 px-2 font-mono text-right">
                          {fmt1(getOmVal(omResult.stats, omWbCol as keyof OmStat, rowPct))}
                        </td>
                        <td className="py-0.5 px-2 font-mono text-right">
                          {fmt1(getOmVal(omResult.stats, omMwbCol as keyof OmStat, rowPct))}
                        </td>
                        <td className="py-0.5 px-2 font-mono text-right">
                          {fmt1(getOmVal(omResult.stats, omMdbCol as keyof OmStat, rowPct))}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {omResult.winterization?.no_freeze_start && (
            <p className="text-xs text-gray-500 mt-2">
              No-freeze: {omResult.winterization.no_freeze_start} → {omResult.winterization.no_freeze_end}
            </p>
          )}
        </Card>
      )}

      {/* ── Psychrometric chart ──────────────────────────────── */}
      <Card title="Psychrometric Chart">
        {!chartSrc && (
          <button
            onClick={loadChart}
            disabled={chartLoading}
            className="w-full bg-gray-100 hover:bg-gray-200 disabled:opacity-50 text-gray-700 font-medium py-2 px-4 rounded-lg text-sm transition-colors"
          >
            {chartLoading ? "Rendering…" : "▶ Generate Psychrometric Chart"}
          </button>
        )}
        {chartError && <p className="text-red-500 text-sm mt-2">{chartError}</p>}
        {chartSrc && (
          <>
            <img src={chartSrc} alt="Psychrometric chart" className="w-full rounded-lg mt-2" />
            <button
              onClick={() => setChartSrc(null)}
              className="mt-2 text-xs text-gray-400 hover:text-gray-600"
            >
              ✕ Clear
            </button>
          </>
        )}
      </Card>
    </div>
  );
}
