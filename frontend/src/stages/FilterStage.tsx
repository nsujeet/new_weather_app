/**
 * FilterStage — score filters, show coverage table, user picks one.
 * Mirrors Streamlit Stage 3.
 */
import { useEffect, useState } from "react";
import { useStore } from "../store";
import { scoreFilters, processData, getOpenMeteo } from "../api";
import Card from "../components/Card";

const QC_OPTIONS = ["0", "1", "2", "3", "4", "5", "6", "9"];
const QC_LABELS: Record<string, string> = {
  "0": "0 - passed", "1": "1 - passed/replaced",
  "2": "2 - suspect", "3": "3 - erroneous",
  "4": "4 - estimated", "5": "5 - interpolated",
  "6": "6 - not available", "9": "9 - missing",
};

export default function FilterStage() {
  const {
    fetchToken, lat, lon, siteInfo, selectedStation, selectedYears, units,
    filterScores, selectedFilter, excludeQualityCodes, clipLower, clipUpper,
    omResult, omLoading,
    setFilterScores, setSelectedFilter, setExcludeQualityCodes, setClipLower, setClipUpper,
    setProcessResult, advanceTo, setStage,
    setOmResult, setOmLoading, setOmError,
  } = useStore();

  const [scoring,    setScoring]    = useState(false);
  const [processing, setProcessing] = useState(false);
  const [error,      setError]      = useState<string | null>(null);
  const [omStatus,   setOmStatus]   = useState<"idle"|"loading"|"done"|"error">("idle");
  const [omErrMsg,   setOmErrMsg]   = useState<string | null>(null);

  // Auto-score on mount if not yet done
  useEffect(() => {
    if (filterScores || !fetchToken) return;
    runScoring();
  }, [fetchToken]);

  // Fallback: fire OM only if SiteStage didn't already get it — always last 15 years
  useEffect(() => {
    if (omResult || omLoading || lat == null || lon == null) return;
    const omEnd   = new Date().getFullYear() - 1;
    const omStart = omEnd - 14;
    console.log("[FilterStage] firing OM fallback", { lat, lon, omStart, omEnd });
    setOmStatus("loading");
    setOmLoading(true);
    setOmError(null);
    getOpenMeteo(lat, lon, omStart, omEnd, units)
      .then((r) => {
        console.log("[FilterStage] OM success", r);
        setOmResult(r);
        setOmLoading(false);
        setOmStatus("done");
      })
      .catch((e: unknown) => {
        const err = e as { response?: { data?: { error?: string; detail?: string } }; message?: string };
        const msg = err?.response?.data?.error ?? err?.response?.data?.detail ?? err?.message ?? "Open-Meteo failed";
        console.error("[FilterStage] OM error", msg);
        setOmError(msg);
        setOmLoading(false);
        setOmErrMsg(msg);
        setOmStatus("error");
      });
  }, []);

  const runScoring = async () => {
    if (!fetchToken) return;
    setScoring(true);
    setError(null);
    try {
      const r = await scoreFilters(fetchToken, excludeQualityCodes);
      setFilterScores(r.filters);
      if (!selectedFilter) setSelectedFilter(r.recommended);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Filter scoring failed");
    } finally {
      setScoring(false);
    }
  };

  const handleConfirm = async () => {
    if (!fetchToken || !selectedFilter || lat == null || lon == null || !selectedStation) return;
    setProcessing(true);
    setError(null);
    try {
      const result = await processData(fetchToken, {
        station_id: selectedStation,
        years: selectedYears,
        units,
        lat,
        lon,
        elevation_m: siteInfo?.elevation_m ?? 0,
        filter_type: selectedFilter,
        exclude_quality_codes: excludeQualityCodes,
        clip_lower_f: clipLower,
        clip_upper_f: clipUpper ?? undefined,
      });
      setProcessResult(result);
      advanceTo("results");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Processing failed");
    } finally {
      setProcessing(false);
    }
  };

  return (
    <Card title="4. Filter & Process">
      <button onClick={() => setStage("fetch")} className="text-xs text-blue-600 hover:underline mb-3 block">
        ← Change years / re-download
      </button>

      {/* Quality code selector */}
      <div className="mb-4">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Exclude quality codes
        </p>
        <div className="flex flex-wrap gap-2">
          {QC_OPTIONS.map((code) => {
            const excluded = excludeQualityCodes.includes(code);
            return (
              <button
                key={code}
                onClick={() => {
                  const next = excluded
                    ? excludeQualityCodes.filter((c) => c !== code)
                    : [...excludeQualityCodes, code];
                  setExcludeQualityCodes(next);
                  setFilterScores(null); // invalidate so re-scoring runs
                }}
                className={`text-xs px-2 py-1 rounded border transition-colors ${
                  excluded
                    ? "bg-[#2a1a1a] border-[#5a2020] text-[#ff8080]"
                    : "bg-[#1a1d27] border-[#2e3148] text-[#8b90a8] hover:border-[#4f8ef7]"
                }`}
              >
                {excluded ? "✕ " : "✓ "}{QC_LABELS[code] ?? code}
              </button>
            );
          })}
        </div>
        {filterScores && (
          <button
            onClick={runScoring}
            className="mt-2 text-xs text-blue-600 hover:underline"
          >
            ↺ Re-score with updated codes
          </button>
        )}
      </div>

      {/* Temperature clipping */}
      <div className="mb-4">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Temperature clipping
        </p>
        <div className="flex flex-wrap gap-4 items-center">
          <label className="flex items-center gap-2 text-xs text-[#8b90a8]">
            Lower clip (°F)
            <input
              type="number"
              value={clipLower}
              onChange={(e) => setClipLower(Number(e.target.value))}
              className="w-16 px-2 py-1 rounded border border-[#2e3148] bg-[#1a1d27] text-[#c0c4d8] text-xs font-mono focus:border-[#4f8ef7] outline-none"
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-[#8b90a8]">
            <input
              type="checkbox"
              checked={clipUpper !== null}
              onChange={(e) => setClipUpper(e.target.checked ? 120 : null)}
              className="accent-[#4f8ef7]"
            />
            Upper clip (°F)
            {clipUpper !== null && (
              <input
                type="number"
                value={clipUpper}
                onChange={(e) => setClipUpper(Number(e.target.value))}
                className="w-16 px-2 py-1 rounded border border-[#2e3148] bg-[#1a1d27] text-[#c0c4d8] text-xs font-mono focus:border-[#4f8ef7] outline-none"
              />
            )}
          </label>
        </div>
      </div>

      {/* Scoring state */}
      {scoring && (
        <p className="text-sm text-gray-500 animate-pulse mb-4">Scoring filters…</p>
      )}

      {/* Filter table */}
      {filterScores && !scoring && (
        <div className="mb-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
            Data coverage by filter type
          </p>
          <div className="space-y-2">
            {filterScores.map((f) => {
              const isSelected = f.name === selectedFilter;
              const barWidth = `${Math.min(f.coverage_pct, 100)}%`;
              return (
                <button
                  key={f.name}
                  onClick={() => setSelectedFilter(f.name)}
                  disabled={!!f.error}
                  className={`w-full text-left p-3 rounded-lg border text-sm transition-colors ${
                    isSelected
                      ? "border-[#4f8ef7] bg-[#1e2a4a]"
                      : "border-[#2e3148] bg-[#1a1d27] hover:border-[#4f8ef7]"
                  } ${f.error ? "opacity-40 cursor-not-allowed" : ""}`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-medium">
                      {f.label || f.name}
                      {f.recommended && <span className="ml-2 text-xs text-yellow-600">★ recommended</span>}
                    </span>
                    <span className="text-xs text-gray-500">
                      {f.error ? f.error : `${f.coverage_pct}% · ${f.rows.toLocaleString()} rows`}
                    </span>
                  </div>
                  {!f.error && (
                    <div className="w-full bg-gray-100 rounded-full h-1.5">
                      <div
                        className={`h-1.5 rounded-full ${f.coverage_pct > 80 ? "bg-green-500" : f.coverage_pct > 50 ? "bg-yellow-400" : "bg-red-400"}`}
                        style={{ width: barWidth }}
                      />
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {error && <p className="text-red-500 text-sm mb-3">{error}</p>}

      {/* Open-Meteo ERA5 status */}
      {omStatus !== "idle" && (
        <div className={`flex justify-between items-center text-xs px-3 py-2 rounded mb-3 ${
          omStatus === "error"   ? "bg-red-950 border border-red-800" :
          omStatus === "done"    ? "bg-green-950 border border-green-800" :
                                   "bg-blue-950 border border-blue-800"
        }`}>
          <span className="text-gray-400">🌐 Open-Meteo ERA5</span>
          {omStatus === "loading" && <span className="text-blue-400 animate-pulse">fetching…</span>}
          {omStatus === "done"    && <span className="text-green-400">✓ ready — will appear in results</span>}
          {omStatus === "error"   && <span className="text-red-400 break-all">✗ {omErrMsg}</span>}
        </div>
      )}

      <button
        onClick={handleConfirm}
        disabled={!selectedFilter || scoring || processing}
        className="wa-btn wa-btn-primary"
      >
        {processing ? "Processing…" : selectedFilter ? `✓ Run with ${selectedFilter} →` : "Select a filter to continue"}
      </button>
    </Card>
  );
}

