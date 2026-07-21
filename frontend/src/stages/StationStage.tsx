/**
 * StationStage — map + NOAA station cards + ASHRAE cards + ERA5 Quick Estimate
 */
import { useEffect, useState, Suspense, lazy } from "react";
import { useStore } from "../store";
import { getStations, getAshraConditions, getPsychroChart, getDensityData, getHeatmapData, getFreezingData, getOpenMeteo, getBulkAvailability } from "../api";
import type { AshraConditionResult, OmStat } from "../api";
import Card from "../components/Card";
import {
  XAxis, YAxis, Tooltip as RCTooltip,
  CartesianGrid, ResponsiveContainer, BarChart, Bar,
} from "recharts";

const SiteMap = lazy(() => import("../components/SiteMap"));

const EDITIONS = ["2025", "2021", "2017", "2013", "2009"] as const;

const STATUS_DOT: Record<string, string> = {
  green:  "bg-green-500",
  yellow: "bg-yellow-400",
  red:    "bg-red-500",
};

function fmt(n: number | undefined | null, unit: string, digits = 0) {
  return n != null ? `${n.toFixed(digits)} ${unit}` : "—";
}

function fmtT(v: number | null | undefined, sfx: string) {
  return v != null ? `${v.toFixed(1)}${sfx}` : "—";
}

// ── getRowVal helper (mirrors ResultsStage) ───────────────────────
function getRowVal(stats: OmStat[], col: string, pct: number): number | null {
  if (!stats?.length) return null;
  let row = stats.find((r) => Number(r["%"]) === pct);
  if (!row) row = stats.reduce((best, r) => Math.abs(Number(r["%"]) - pct) < Math.abs(Number(best["%"]) - pct) ? r : best);
  const v = (row as unknown as Record<string, unknown>)[col];
  return v != null && !Number.isNaN(Number(v)) ? Number(v) : null;
}

export default function StationStage() {
  const {
    lat, lon, siteInfo, units,
    noaaStations, ashraStations, selectedStation, recommendedStationId, ashraConditions,
    ashraEdition: edition, ashraLevel: acfLevel,
    omResult, omLoading, omError,
    stationAvailMap, setStationAvailMap,
    setStations, selectStation, setAshraConditions, setAshraEdition: setEdition, setAshraLevel: setAcfLevel, advanceTo,
    setOmResult, setOmLoading, setOmError, setAvailableYears,
  } = useStore();

  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState<string | null>(null);
  const [noaaError,    setNoaaError]    = useState<string | null>(null);
  const [ashraLoading, setAshraLoading] = useState(false);
  const [availLoading, setAvailLoading] = useState(false);

  // ERA5 quick-estimate section
  const [era5Open,       setEra5Open]       = useState(true);
  const [chartError,     setChartError]     = useState<string | null>(null);

  // Resolve a valid om_token — refetches ERA5 if server was restarted and token expired
  const resolveOmToken = async (): Promise<string | null> => {
    if (omResult?.om_token) {
      return omResult.om_token;
    }
    if (lat == null || lon == null) return null;
    setChartError(null);
    setOmLoading(true);
    try {
      const omEnd   = new Date().getFullYear() - 1;
      const omStart = omEnd - 14;
      const fresh = await getOpenMeteo(lat, lon, omStart, omEnd, units);
      setOmResult(fresh);
      setOmLoading(false);
      return fresh.om_token ?? null;
    } catch (e) {
      setOmError(e instanceof Error ? e.message : "ERA5 refetch failed");
      setOmLoading(false);
      return null;
    }
  };
  type DensityResult = { cells: {x:number;y:number;v:number}[]; x_width:number; y_height:number; max_v:number };
  const [scatterDensity, setScatterDensity] = useState<DensityResult | null>(null);
  const [scatterLoading, setScatterLoading] = useState(false);
  const [psychroB64,     setPsychroB64]     = useState<string | null>(null);
  const [psychroLoading, setPsychroLoading] = useState(false);
  const [heatCells,      setHeatCells]      = useState<{month:string;year:number;value:number}[]|null>(null);
  const [heatLoading,    setHeatLoading]    = useState(false);
  const [freezeBars,     setFreezeBars]     = useState<{week:number;hours:number}[]|null>(null);
  const [freezeLoading,  setFreezeLoading]  = useState(false);

  const sfx    = units === "C" ? "°C" : "°F";
  const si_ip  = units === "C" ? "SI" : "IP";

  // Load NOAA + ASHRAE stations on mount
  useEffect(() => {
    if (noaaStations.length > 0) return;
    if (lat == null || lon == null) return;
    setLoading(true);
    getStations(lat, lon, siteInfo?.elevation_m ?? 0)
      .then((r) => {
        setStations(r.noaa, r.ashrae, r.recommended_station_id);
        if (r.noaa_error) setNoaaError(r.noaa_error);

        // Background: check full availability (2000→now) for all ranked stations.
        // Results go into the store so YearsStage can reuse them without a second call.
        const ids = r.noaa.map((s) => s.GHCN_ID);
        if (ids.length > 0) {
          setAvailLoading(true);
          getBulkAvailability(ids, 2000, new Date().getFullYear())
            .then((avail) => {
              setStationAvailMap(avail);
              // Auto-promote: if recommended has no data, pick station with most years
              const recId = r.recommended_station_id ?? ids[0];
              if ((avail[recId]?.length ?? 0) === 0) {
                const best = ids
                  .map((id) => ({ id, n: avail[id]?.length ?? 0 }))
                  .sort((a, b) => b.n - a.n)[0];
                if (best && best.n > 0) selectStation(best.id);
              }
            })
            .catch(() => {})
            .finally(() => setAvailLoading(false));
        }
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Station lookup failed"))
      .finally(() => setLoading(false));
  }, [lat, lon]);

  // Fetch ASHRAE conditions whenever edition or stations change
  useEffect(() => {
    if (ashraStations.length === 0) return;
    const wmos = ashraStations.map((s) => s.wmo);
    setAshraLoading(true);
    getAshraConditions(wmos, edition, si_ip)
      .then((r) => setAshraConditions(r.results))
      .catch(() => {})
      .finally(() => setAshraLoading(false));
  }, [ashraStations, edition, si_ip]);

  const condByWmo: Record<string, AshraConditionResult> = {};
  for (const c of ashraConditions) condByWmo[c.wmo] = c;

  return (
    <Card title="2. NOAA Station">

      {/* ── ERA5 Quick Estimate — shown first so results are visible immediately ── */}
      <div className="mb-4">
        <button
          onClick={() => setEra5Open((o) => !o)}
          className="w-full flex items-center justify-between px-3 py-2 rounded-lg border text-sm font-semibold transition-colors"
          style={{ borderColor: "var(--wa-border)", background: "var(--wa-surface)", color: "var(--wa-text)" }}
        >
          <span>⚡ ERA5 Quick Estimate (15-year) + ASHRAE</span>
          <span className="text-xs text-gray-500">{era5Open ? "▲ hide" : "▼ show"}</span>
        </button>

        {era5Open && (
          <div className="mt-2 p-3 rounded-lg border" style={{ borderColor: "var(--wa-border)", background: "var(--wa-surface)" }}>
            {omLoading && !omResult && (
              <p className="text-xs text-blue-400 animate-pulse">Fetching ERA5 data…</p>
            )}
            {omError && !omResult && (
              <p className="text-xs text-orange-400">ERA5 unavailable: {omError}</p>
            )}

            {omResult && (() => {
              const pct = Number(acfLevel);
              const isSI = units === "C";
              const sfx  = isSI ? "°C" : "°F";
              const dbCol  = isSI ? "DB_C"   : "DB_F";
              const wbCol  = isSI ? "WB_C"   : "WB_F";
              const mwbCol = isSI ? "MCWB_C" : "MCWB_F";
              const mdbCol = isSI ? "MCDB_C" : "MCDB_F";
              const pUnit  = isSI ? "kPa" : "psia";

              const omDb  = getRowVal(omResult.stats, dbCol,  pct);
              const omWb  = getRowVal(omResult.stats, wbCol,  pct);
              const omMwb = getRowVal(omResult.stats, mwbCol, pct);
              const omMdb = getRowVal(omResult.stats, mdbCol, pct);
              const omPres   = siteInfo ? (isSI ? siteInfo.pressure_kpa.toFixed(3) : siteInfo.pressure_psi.toFixed(3)) : "—";
              const siteElevFt = siteInfo?.elevation_ft;

              const metrics: { label: string; om?: number | null; omStr?: string; isMeta?: boolean }[] = [
                { label: `${pct}% Tdb (${sfx})`,    om: omDb   },
                { label: `${pct}% Twb (${sfx})`,    om: omWb   },
                { label: `MCWB @ Tdb (${sfx})`,     om: omMwb  },
                { label: `MCDB @ Twb (${sfx})`,     om: omMdb  },
                { label: `Site pressure (${pUnit})`, omStr: omPres },
                { label: "Distance (mi)",            omStr: "at site",                                              isMeta: true },
                { label: "Elevation (ft)",           omStr: siteElevFt != null ? siteElevFt.toFixed(0) : "—",      isMeta: true },
                { label: "Δ Elevation (ft)",         omStr: "0",                                                    isMeta: true },
              ];

              return (
                <>
                  <div className="overflow-x-auto mb-3">
                    <table className="w-full text-xs border-collapse">
                      <thead>
                        <tr>
                          <th className="text-left py-1 pr-3 text-gray-500 font-semibold whitespace-nowrap">Metric</th>
                          <th className="text-right py-1 px-2 text-blue-400 font-semibold whitespace-nowrap">🌐 ERA5</th>
                          {ashraStations.map((s, i) => {
                            const cond = condByWmo[s.wmo];
                            const name = cond?.station ?? s.station;
                            return (
                              <th key={s.wmo} className="text-right py-1 px-2 font-semibold whitespace-nowrap" style={{ color: "var(--wa-text-dim)" }}>
                                📊 {i === 0 ? "⭐ " : ""}{name.split(",")[0]}
                              </th>
                            );
                          })}
                        </tr>
                      </thead>
                      <tbody>
                        {metrics.map(({ label, om, omStr, isMeta }, ri) => (
                          <tr key={label} className={ri % 2 === 0 ? "bg-[#1a1d27]" : ""}>
                            <td className={`py-1 pr-3 whitespace-nowrap ${isMeta ? "text-gray-500" : "text-gray-400"}`}>{label}</td>
                            <td className="text-right py-1 px-2 font-mono text-blue-300">
                              {omStr ?? (om != null ? om.toFixed(1) : "—")}
                            </td>
                            {ashraStations.map((s) => {
                              const cond = condByWmo[s.wmo];
                              const lv   = cond?.levels?.[acfLevel];
                              let val: string = "—";
                              if (ri === 5) {
                                val = s.dist_miles != null ? s.dist_miles.toFixed(1) : "—";
                              } else if (ri === 6) {
                                val = s.elev_ft != null ? s.elev_ft.toFixed(0) : "—";
                              } else if (ri === 7) {
                                val = (s.elev_ft != null && siteElevFt != null)
                                  ? Math.abs(s.elev_ft - siteElevFt).toFixed(0)
                                  : "—";
                              } else {
                                val = ashraLoading ? "…" : "—";
                                if (lv) {
                                  if      (ri === 0) val = lv.tdb  != null ? lv.tdb.toFixed(1)  : "—";
                                  else if (ri === 1) val = lv.twb  != null ? lv.twb.toFixed(1)  : "—";
                                  else if (ri === 2) val = lv.mcwb != null ? lv.mcwb.toFixed(1) : "—";
                                  else if (ri === 3) val = lv.mcdb != null ? lv.mcdb.toFixed(1) : "—";
                                  else if (ri === 4) val = cond?.pressure_psia != null ? cond.pressure_psia.toFixed(3) : "—";
                                }
                              }
                              return (
                                <td key={s.wmo} className={`text-right py-1 px-2 font-mono ${isMeta ? "text-gray-500" : ""}`} style={isMeta ? {} : { color: "var(--wa-text-dim)" }}>
                                  {val}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {omResult.winterization.no_freeze_start && omResult.winterization.no_freeze_end && (
                    <div className="text-xs px-3 py-2 rounded mb-3 bg-blue-950 border border-blue-800 text-blue-300">
                      No-freeze window: <strong>{omResult.winterization.no_freeze_start}</strong> → <strong>{omResult.winterization.no_freeze_end}</strong>
                    </div>
                  )}

                  {/* Chart error */}
                  {chartError && (
                    <p className="text-xs text-red-400 mb-2 px-1">{chartError}</p>
                  )}

                  {/* Weather density chart (Tdb vs Twb) */}
                  <div className="mb-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-semibold text-gray-400">Weather density — Tdb vs Twb (15-yr hourly)</span>
                      <button onClick={async () => {
                        if (scatterLoading) return;
                        if (scatterDensity) { setScatterDensity(null); return; }
                        setScatterLoading(true); setChartError(null);
                        try {
                          const tok = await resolveOmToken();
                          if (!tok) { setChartError("ERA5 token unavailable"); return; }
                          const d = await getDensityData(tok, units, 60);
                          setScatterDensity(d);
                        } catch (e) { setChartError("Density: " + (e instanceof Error ? e.message : String(e))); }
                        finally { setScatterLoading(false); }
                      }} className="text-xs px-2 py-0.5 rounded border border-[#2e3148] text-[#8b90a8] hover:border-[#4f8ef7] transition-colors">
                        {scatterLoading ? "…" : scatterDensity ? "↺ reset" : "▶ run chart"}
                      </button>
                    </div>
                    {scatterDensity && (() => {
                      const { cells, x_width, y_height, max_v } = scatterDensity;
                      if (!cells.length) return <p className="text-xs text-gray-500">No data</p>;
                      const xs = cells.map(c => c.x), ys = cells.map(c => c.y);
                      const minX = Math.min(...xs) - x_width / 2;
                      const maxX = Math.max(...xs) + x_width / 2;
                      const minY = Math.min(...ys) - y_height / 2;
                      const maxY = Math.max(...ys) + y_height / 2;
                      const rX = maxX - minX, rY = maxY - minY;
                      const PAD_L = 32, PAD_B = 20, PAD_R = 6, PAD_T = 4;
                      const VW = 360, VH = 210;
                      const cW = VW - PAD_L - PAD_R, cH = VH - PAD_T - PAD_B;
                      const px = (x: number) => PAD_L + ((x - minX) / rX) * cW;
                      const py = (y: number) => PAD_T + ((maxY - y) / rY) * cH;
                      const cellPxW = (x_width / rX) * cW + 0.5;
                      const cellPxH = (y_height / rY) * cH + 0.5;
                      const col = (v: number) => {
                        const t = Math.pow(v / max_v, 0.35);
                        const r = Math.round(t > 0.5 ? 255 : t * 2 * 255);
                        const g = Math.round(t < 0.5 ? t * 2 * 180 : 180 - (t - 0.5) * 2 * 80);
                        const b = Math.round(t > 0.5 ? 0 : (1 - t * 2) * 220);
                        return `rgb(${r},${g},${b})`;
                      };
                      const xTicks = 5, yTicks = 4;
                      return (
                        <svg viewBox={`0 0 ${VW} ${VH}`} width="100%" style={{ display: "block" }}>
                          {cells.map((c, i) => (
                            <rect key={i} x={px(c.x - x_width/2)} y={py(c.y + y_height/2)} width={cellPxW} height={cellPxH} fill={col(c.v)} opacity={0.92} />
                          ))}
                          {/* axes */}
                          <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={PAD_T + cH} stroke="#4e5270" />
                          <line x1={PAD_L} y1={PAD_T + cH} x2={PAD_L + cW} y2={PAD_T + cH} stroke="#4e5270" />
                          {Array.from({length: xTicks}, (_, i) => {
                            const v = minX + (i / (xTicks - 1)) * rX;
                            const x = px(v);
                            return <g key={i}><line x1={x} y1={PAD_T+cH} x2={x} y2={PAD_T+cH+3} stroke="#4e5270" /><text x={x} y={VH-2} textAnchor="middle" fontSize={8} fill="#6b7280">{v.toFixed(0)}</text></g>;
                          })}
                          {Array.from({length: yTicks}, (_, i) => {
                            const v = minY + (i / (yTicks - 1)) * rY;
                            const y = py(v);
                            return <g key={i}><line x1={PAD_L-3} y1={y} x2={PAD_L} y2={y} stroke="#4e5270" /><text x={PAD_L-5} y={y+3} textAnchor="end" fontSize={8} fill="#6b7280">{v.toFixed(0)}</text></g>;
                          })}
                          <text x={PAD_L + cW/2} y={VH} textAnchor="middle" fontSize={9} fill="#8b90a8">Tdb ({sfx})</text>
                          <text x={8} y={PAD_T + cH/2} textAnchor="middle" fontSize={9} fill="#8b90a8" transform={`rotate(-90,8,${PAD_T+cH/2})`}>Twb ({sfx})</text>
                        </svg>
                      );
                    })()}
                  </div>

                  {/* Psychrometric chart */}
                  <div className="mb-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-semibold text-gray-400">Psychrometric chart</span>
                      <button onClick={async () => {
                        if (psychroLoading) return;
                        if (psychroB64) { setPsychroB64(null); return; }
                        setPsychroLoading(true); setChartError(null);
                        try {
                          const tok = await resolveOmToken();
                          if (!tok) { setChartError("ERA5 token unavailable"); return; }
                          const d = await getPsychroChart(tok, units);
                          setPsychroB64(d.image_b64);
                        } catch (e) { setChartError("Psychro: " + (e instanceof Error ? e.message : String(e))); }
                        finally { setPsychroLoading(false); }
                      }} className="text-xs px-2 py-0.5 rounded border border-[#2e3148] text-[#8b90a8] hover:border-[#4f8ef7] transition-colors">
                        {psychroLoading ? "…" : psychroB64 ? "↺ reset" : "▶ run chart"}
                      </button>
                    </div>
                    {psychroB64 && <img src={`data:image/png;base64,${psychroB64}`} alt="Psychrometric chart" className="w-full rounded" />}
                  </div>

                  {/* Freezing hours */}
                  <div className="mb-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-semibold text-gray-400">Freezing hours per fiscal week</span>
                      <button onClick={async () => {
                        if (freezeLoading) return;
                        if (freezeBars) { setFreezeBars(null); return; }
                        setFreezeLoading(true); setChartError(null);
                        try {
                          const tok = await resolveOmToken();
                          if (!tok) { setChartError("ERA5 token unavailable"); return; }
                          const r = await getFreezingData(tok);
                          setFreezeBars(r.bars);
                        } catch (e) { setChartError("Freezing: " + (e instanceof Error ? e.message : String(e))); }
                        finally { setFreezeLoading(false); }
                      }} className="text-xs px-2 py-0.5 rounded border border-[#2e3148] text-[#8b90a8] hover:border-[#4f8ef7] transition-colors">
                        {freezeLoading ? "…" : freezeBars ? "↺ reset" : "▶ run chart"}
                      </button>
                    </div>
                    {freezeBars && freezeBars.length > 0 && (
                      <ResponsiveContainer width="100%" height={180}>
                        <BarChart data={freezeBars} margin={{ top: 4, right: 8, bottom: 18, left: 20 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#2e3148" />
                          <XAxis dataKey="week" label={{ value: "Fiscal week", position: "insideBottom", offset: -8, fontSize: 10, fill: "#8b90a8" }} tick={{ fontSize: 9, fill: "#8b90a8" }} />
                          <YAxis tick={{ fontSize: 9, fill: "#8b90a8" }} />
                          <RCTooltip contentStyle={{ background: "#1a1d27", border: "1px solid #2e3148", fontSize: 11 }} formatter={(v: number) => [`${v} hrs`, "Hours below 36°F"]} />
                          <Bar dataKey="hours" fill="#378ADD" barSize={6} />
                        </BarChart>
                      </ResponsiveContainer>
                    )}
                  </div>

                  {/* Min temp heatmap */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-semibold text-gray-400">Min temperature heatmap</span>
                      <button onClick={async () => {
                        if (heatLoading) return;
                        if (heatCells) { setHeatCells(null); return; }
                        setHeatLoading(true); setChartError(null);
                        try {
                          const tok = await resolveOmToken();
                          if (!tok) { setChartError("ERA5 token unavailable"); return; }
                          const r = await getHeatmapData(tok, units);
                          setHeatCells(r.cells);
                        } catch (e) { setChartError("Heatmap: " + (e instanceof Error ? e.message : String(e))); }
                        finally { setHeatLoading(false); }
                      }} className="text-xs px-2 py-0.5 rounded border border-[#2e3148] text-[#8b90a8] hover:border-[#4f8ef7] transition-colors">
                        {heatLoading ? "…" : heatCells ? "↺ reset" : "▶ run chart"}
                      </button>
                    </div>
                    {heatCells && heatCells.length > 0 && (() => {
                      const years  = [...new Set(heatCells.map((c) => c.year))].sort();
                      const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
                      const lookup: Record<string, number> = {};
                      heatCells.forEach((c) => { lookup[`${c.month}-${c.year}`] = c.value; });
                      const minV = Math.min(...heatCells.map((c) => c.value));
                      const maxV = Math.max(...heatCells.map((c) => c.value));
                      const colour = (v: number) => { const t = (v - minV) / (maxV - minV || 1); const r = Math.round(220 - t * 170); const g = Math.round(50 + t * 170); return `rgb(${r},${g},50)`; };
                      return (
                        <div className="overflow-x-auto">
                          <table className="text-xs border-collapse">
                            <thead><tr><th className="px-1 py-0.5 text-gray-500 text-left">Month</th>{years.map((y) => <th key={y} className="px-1 py-0.5 text-gray-500 text-center">{y}</th>)}</tr></thead>
                            <tbody>{months.map((m) => (<tr key={m}><td className="px-1 py-0.5 font-medium text-gray-400">{m}</td>{years.map((y) => { const v = lookup[`${m}-${y}`]; return (<td key={y} className="px-1 py-0.5 text-center font-mono" style={v != null ? { backgroundColor: colour(v), color: "#fff", borderRadius: 2 } : {}}>{v != null ? v.toFixed(1) : ""}</td>); })}</tr>))}</tbody>
                          </table>
                        </div>
                      );
                    })()}
                  </div>
                </>
              );
            })()}
          </div>
        )}
      </div>

      {/* ── Map ── */}
      {lat != null && lon != null && (
        <div className="mb-4">
          <Suspense fallback={<div className="h-[340px] rounded-lg border border-gray-200 flex items-center justify-center text-xs text-gray-400">Loading map…</div>}>
            <SiteMap siteLat={lat} siteLon={lon} siteElevFt={siteInfo?.elevation_ft} noaaStations={noaaStations} ashraStations={ashraStations} selectedStation={selectedStation} onSelectStation={selectStation} />
          </Suspense>
        </div>
      )}

      {/* ── NOAA + ASHRAE station cards ── */}
      {loading ? (
        <p className="text-sm text-gray-500 animate-pulse mb-4">Ranking nearest stations…</p>
      ) : error ? (
        <p className="text-red-500 text-sm mb-4">{error}</p>
      ) : (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
        {/* NOAA cards */}
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
            NOAA Stations
            {availLoading && <span className="ml-2 font-normal normal-case text-[#4f8ef7] animate-pulse">checking data…</span>}
          </p>
          {noaaError && (
            <p className="text-xs text-orange-400 mb-2">
              NOAA unavailable for this location — use ASHRAE reference data instead.
            </p>
          )}
          <div className="space-y-2">
            {noaaStations.map((s) => {
              const selected   = s.GHCN_ID === selectedStation;
              const years      = stationAvailMap[s.GHCN_ID];
              const yearCount  = years?.length ?? null;
              const availBadge = availLoading && yearCount === null ? null : yearCount === null ? null
                : yearCount === 0
                  ? <span className="text-xs px-1.5 py-0.5 rounded bg-red-950 border border-red-800 text-red-400 whitespace-nowrap">No data</span>
                  : yearCount < 5
                    ? <span className="text-xs px-1.5 py-0.5 rounded bg-yellow-950 border border-yellow-800 text-yellow-400 whitespace-nowrap">{yearCount} yrs</span>
                    : <span className="text-xs px-1.5 py-0.5 rounded bg-green-950 border border-green-800 text-green-400 whitespace-nowrap">{yearCount} yrs</span>;
              return (
                <button
                  key={s.GHCN_ID}
                  onClick={() => selectStation(s.GHCN_ID)}
                  className={`w-full text-left p-3 rounded-lg border text-sm transition-colors ${
                    selected ? "border-[#4f8ef7] bg-[#1e2a4a]" : "border-[#2e3148] bg-[#1a1d27] hover:border-[#4f8ef7]"
                  }`}
                >
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${STATUS_DOT[s.recommendation_status ?? ""] ?? "bg-gray-300"}`} />
                    {s.GHCN_ID === recommendedStationId && <span className="text-yellow-500 text-xs">★</span>}
                    <span className="font-medium truncate">{s.NAME}</span>
                    {availBadge && <span className="ml-auto shrink-0">{availBadge}</span>}
                  </div>
                  <p className="text-xs text-gray-400">
                    {s.GHCN_ID} · {fmt(s.dist_miles, "mi", 1)} · Δelev {fmt(s.elev_delta_ft, "ft")}
                  </p>
                </button>
              );
            })}
          </div>
        </div>

        {/* ASHRAE cards */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              ASHRAE Reference
              {ashraLoading && <span className="ml-2 font-normal normal-case text-[#4f8ef7] animate-pulse">fetching…</span>}
            </p>
          </div>

          {/* Edition selector */}
          <div className="flex flex-wrap gap-1 mb-1">
            <span className="text-xs text-gray-500 self-center mr-1">Edition:</span>
            {EDITIONS.map((ed) => (
              <button
                key={ed}
                onClick={() => setEdition(ed)}
                className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                  edition === ed
                    ? "bg-[#4f8ef7] text-white border-[#4f8ef7]"
                    : "bg-[#1a1d27] text-[#8b90a8] border-[#2e3148] hover:border-[#4f8ef7]"
                }`}
              >
                {ed}
              </button>
            ))}
          </div>

          {/* Level selector */}
          <div className="flex flex-wrap gap-1 mb-3">
            <span className="text-xs text-gray-500 self-center mr-1">Level:</span>
            {(["0.4", "1", "2"] as const).map((lk) => (
              <button
                key={lk}
                onClick={() => setAcfLevel(lk)}
                className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                  acfLevel === lk
                    ? "bg-[#a855f7] text-white border-[#a855f7]"
                    : "bg-[#1a1d27] text-[#8b90a8] border-[#2e3148] hover:border-[#a855f7]"
                }`}
              >
                {lk}%
              </button>
            ))}
          </div>

          <div className={`space-y-2 transition-opacity ${ashraLoading ? "opacity-40" : "opacity-100"}`}>
            {ashraStations.map((s, i) => {
              const cond = condByWmo[s.wmo];
              const lv   = cond?.levels?.[acfLevel];
              const servedEdition = cond?.ashrae_version;
              return (
                <div key={s.wmo} className="p-3 rounded-lg border text-sm" style={{ borderColor: "var(--wa-border)", background: "var(--wa-surface)" }}>
                  <div className="flex items-center gap-1 mb-0.5">
                    {i === 0 && <span className="text-yellow-500 text-xs">★</span>}
                    <span className="font-medium truncate">{cond?.station ?? s.station}</span>
                    {servedEdition && (
                      <span className={`text-xs ml-1 px-1 rounded ${servedEdition !== edition ? "text-amber-500 bg-amber-950" : "text-gray-500"}`}>
                        {servedEdition}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400 mb-1">
                    WMO {s.wmo} · {fmt(s.dist_miles, "mi", 1)} · {fmt(s.elev_ft, "ft")}
                    {cond?.pressure_psia && ` · ${cond.pressure_psia.toFixed(3)} psia`}
                  </p>
                  {lv && !cond?.error && (
                    <div className="flex flex-wrap gap-1 mt-1">
                      <span className="text-xs px-2 py-0.5 rounded-full bg-red-950 border border-red-800 text-red-300 whitespace-nowrap">
                        {acfLevel}% DB {fmtT(lv.tdb, sfx)} / MCWB {fmtT(lv.mcwb, sfx)}
                      </span>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-green-950 border border-green-800 text-green-300 whitespace-nowrap">
                        {acfLevel}% WB {fmtT(lv.twb, sfx)} / MCDB {fmtT(lv.mcdb, sfx)}
                      </span>
                    </div>
                  )}
                  {cond?.error && (
                    <p className="text-xs text-gray-500 mt-1">Conditions unavailable</p>
                  )}
                  {!cond && !ashraLoading && (
                    <p className="text-xs text-gray-500 mt-1 animate-pulse">Loading…</p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      )}

      <button
        onClick={() => {
          // Pre-populate years from bulk check so YearsStage skips its own call
          const cached = selectedStation ? stationAvailMap[selectedStation] : undefined;
          if (cached && cached.length > 0) setAvailableYears(cached);
          advanceTo("years");
        }}
        disabled={!selectedStation}
        className="wa-btn wa-btn-primary"
      >
        {selectedStation ? `✓ Confirm — ${selectedStation}` : "Select a station to continue"}
      </button>
    </Card>
  );
}

