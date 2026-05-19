/**
 * StationStage — map + NOAA station cards + ASHRAE cards + ERA5 Quick Estimate
 */
import { useEffect, useState, Suspense, lazy } from "react";
import { useStore } from "../store";
import { getStations, getAshraConditions, getPsychroChart, getScatterData, getHeatmapData, getFreezingData, getOpenMeteo } from "../api";
import type { AshraConditionResult, OmStat } from "../api";
import Card from "../components/Card";
import {
  ScatterChart, Scatter, XAxis, YAxis, Tooltip as RCTooltip,
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
    setStations, selectStation, setAshraConditions, setAshraEdition: setEdition, setAshraLevel: setAcfLevel, advanceTo,
    setOmResult, setOmLoading, setOmError,
  } = useStore();

  const [loading,      setLoading]      = useState(false);
  const [error,        setError]        = useState<string | null>(null);
  const [ashraLoading, setAshraLoading] = useState(false);

  // ERA5 quick-estimate section
  const [era5Open,       setEra5Open]       = useState(true);
  const [chartError,     setChartError]     = useState<string | null>(null);

  // Resolve a valid om_token — refetches ERA5 if server was restarted and token expired
  const resolveOmToken = async (): Promise<string | null> => {
    if (omResult?.om_token) {
      // Quick probe: try to fetch 1-row scatter; if 404 fall through to refetch
      try {
        await getScatterData(omResult.om_token, units);
        return omResult.om_token;
      } catch { /* token expired — fall through */ }
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
  const [scatterPoints,  setScatterPoints]  = useState<{x: number; y: number}[] | null>(null);
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
      .then((r) => setStations(r.noaa, r.ashrae, r.recommended_station_id))
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
              const omPres = siteInfo ? (isSI ? siteInfo.pressure_kpa.toFixed(3) : siteInfo.pressure_psi.toFixed(3)) : "—";

              const metrics: { label: string; om?: number | null; omStr?: string }[] = [
                { label: `${pct}% Tdb (${sfx})`,    om: omDb   },
                { label: `${pct}% Twb (${sfx})`,    om: omWb   },
                { label: `MCWB @ Tdb (${sfx})`,     om: omMwb  },
                { label: `MCDB @ Twb (${sfx})`,     om: omMdb  },
                { label: `Site pressure (${pUnit})`, omStr: omPres },
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
                        {metrics.map(({ label, om, omStr }, ri) => (
                          <tr key={label} className={ri % 2 === 0 ? "bg-[#1a1d27]" : ""}>
                            <td className="py-1 pr-3 text-gray-400 whitespace-nowrap">{label}</td>
                            <td className="text-right py-1 px-2 font-mono text-blue-300">
                              {omStr ?? (om != null ? om.toFixed(1) : "—")}
                            </td>
                            {ashraStations.map((s) => {
                              const cond = condByWmo[s.wmo];
                              const lv   = cond?.levels?.[acfLevel];
                              let val: string = ashraLoading ? "…" : "—";
                              if (lv) {
                                if      (ri === 0) val = lv.tdb  != null ? lv.tdb.toFixed(1)  : "—";
                                else if (ri === 1) val = lv.twb  != null ? lv.twb.toFixed(1)  : "—";
                                else if (ri === 2) val = lv.mcwb != null ? lv.mcwb.toFixed(1) : "—";
                                else if (ri === 3) val = lv.mcdb != null ? lv.mcdb.toFixed(1) : "—";
                                else if (ri === 4) val = cond?.pressure_psia != null ? cond.pressure_psia.toFixed(3) : "—";
                              }
                              return (
                                <td key={s.wmo} className="text-right py-1 px-2 font-mono" style={{ color: "var(--wa-text-dim)" }}>
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

                  {/* Scatter chart */}
                  <div className="mb-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-semibold text-gray-400">Weather scatter — Tdb vs Twb</span>
                      <button onClick={async () => {
                        if (scatterPoints) { setScatterPoints(null); return; }
                        setScatterLoading(true); setChartError(null);
                        try {
                          const tok = await resolveOmToken();
                          if (!tok) { setChartError("ERA5 token unavailable"); return; }
                          const d = await getScatterData(tok, units);
                          setScatterPoints(d.points);
                        } catch (e) { setChartError("Scatter: " + (e instanceof Error ? e.message : String(e))); }
                        finally { setScatterLoading(false); }
                      }} className="text-xs px-2 py-0.5 rounded border border-[#2e3148] text-[#8b90a8] hover:border-[#4f8ef7] transition-colors">
                        {scatterLoading ? "…" : scatterPoints ? "↺ reset" : "▶ run chart"}
                      </button>
                    </div>
                    {scatterPoints && (
                      <ResponsiveContainer width="100%" height={200}>
                        <ScatterChart margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
                          <CartesianGrid stroke="#2e3148" strokeDasharray="3 3" />
                          <XAxis dataKey="x" name={`Tdb (${sfx})`} type="number" domain={["auto","auto"]} tick={{ fontSize: 10, fill: "#8b90a8" }} label={{ value: `Tdb (${sfx})`, position: "insideBottom", offset: -2, fontSize: 10, fill: "#8b90a8" }} />
                          <YAxis dataKey="y" name={`Twb (${sfx})`} type="number" domain={["auto","auto"]} tick={{ fontSize: 10, fill: "#8b90a8" }} />
                          <RCTooltip cursor={{ strokeDasharray: "3 3" }} contentStyle={{ background: "#1a1d27", border: "1px solid #2e3148", fontSize: 11 }} formatter={(v: number) => v.toFixed(1)} />
                          <Scatter data={scatterPoints} fill="#4f8ef7" opacity={0.6} r={3} />
                        </ScatterChart>
                      </ResponsiveContainer>
                    )}
                  </div>

                  {/* Psychrometric chart */}
                  <div className="mb-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-semibold text-gray-400">Psychrometric chart</span>
                      <button onClick={async () => {
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
            <SiteMap siteLat={lat} siteLon={lon} noaaStations={noaaStations} selectedStation={selectedStation} onSelectStation={selectStation} />
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
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">NOAA Stations</p>
          <div className="space-y-2">
            {noaaStations.map((s) => {
              const selected = s.GHCN_ID === selectedStation;
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
        onClick={() => advanceTo("years")}
        disabled={!selectedStation}
        className="wa-btn wa-btn-primary"
      >
        Confirm — {selectedStation ?? "select a station"}
      </button>
    </Card>
  );
}

