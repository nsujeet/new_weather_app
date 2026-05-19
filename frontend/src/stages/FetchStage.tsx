/**
 * FetchStage — SSE download from NOAA + concurrent Open-Meteo ERA5 fetch
 */
import { useState } from "react";
import { useStore } from "../store";
import { streamFetch, downloadCsv, getOpenMeteo, type FetchProgress } from "../api";
import Card from "../components/Card";

console.log("[FetchStage] module loaded v2");

interface RowStatus {
  year: number;
  status: string;
  rows: number;
}

type OmStatus = "idle" | "loading" | "done" | "error";

export default function FetchStage() {
  const {
    selectedStation, selectedYears, units, lat, lon,
    omResult,
    setFetchToken, setCachedYears, advanceTo, setStage,
    setOmResult, setOmLoading, setOmError,
  } = useStore();

  const [running,   setRunning]   = useState(false);
  const [pct,       setPct]       = useState(0);
  const [rows,      setRows]      = useState<RowStatus[]>([]);
  const [done,      setDone]      = useState(false);
  const [token,     setToken]     = useState<string | null>(null);
  const [error,     setError]     = useState<string | null>(null);
  const [omStatus,  setOmStatus]  = useState<OmStatus>("idle");
  const [omErrMsg,  setOmErrMsg]  = useState<string | null>(null);

  const handleFetch = async () => {
    console.log("[FetchStage] handleFetch called", { selectedStation, lat, lon, selectedYears });
    if (!selectedStation || lat == null || lon == null) {
      console.warn("[FetchStage] early return — null station/lat/lon");
      return;
    }
    setRunning(true);
    setRows([]);
    setPct(0);
    setDone(false);
    setError(null);

    // Fire Open-Meteo only if SiteStage didn't already fetch it — always use last 15 years
    const omEnd = new Date().getFullYear() - 1;
    const omStart = omEnd - 14;
    let omPromise: Promise<void> = Promise.resolve();
    if (!omResult) {
      console.log("[OM] SiteStage result missing — firing fallback fetch", { lat, lon, omStart, omEnd, units });
      setOmStatus("loading");
      setOmLoading(true);
      setOmError(null);
      omPromise = getOpenMeteo(lat, lon, omStart, omEnd, units)
        .then((r) => {
          console.log("[OM] success", r);
          setOmResult(r);
          setOmLoading(false);
          setOmStatus("done");
        })
        .catch((e: unknown) => {
          const err = e as { response?: { data?: { error?: string; detail?: string } }; message?: string };
          const data = err?.response?.data;
          const msg = data?.error ?? data?.detail ?? err?.message ?? "Open-Meteo failed";
          console.error("[OM] error", msg, e);
          setOmError(msg);
          setOmLoading(false);
          setOmErrMsg(msg);
          setOmStatus("error");
        });
    } else {
      setOmStatus("done");
    }

    try {
      const t = await streamFetch(
        selectedStation,
        selectedYears,
        units,
        (p: FetchProgress) => {
          if (p.event === "progress" && p.year != null && p.year !== 0) {
            setPct(Math.min(p.pct ?? 0, 100));
            setRows((prev) => [
              ...prev.filter((r) => r.year !== p.year),
              { year: p.year!, status: p.status ?? "", rows: p.rows ?? 0 },
            ]);
          }
          if (p.event === "done") {
            setPct(100);
            setDone(true);
            setToken(p.token!);
            if (p.years_loaded) setCachedYears(p.years_loaded);
          }
        }
      );
      setFetchToken(t);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Fetch failed");
    } finally {
      setRunning(false);
    }

    // Let OM finish in background — don't await here, just log if needed
    omPromise.catch(() => { /* already handled above */ });
  };

  const STATUS_LABEL: Record<string, string> = {
    ok:      "downloaded",
    memory:  "from cache",
    disk:    "from disk cache",
    fetched: "downloaded",
    error:   "error",
    empty:   "no data",
    failed:  "failed",
  };
  const STATUS_COLOR: Record<string, string> = {
    ok:      "text-green-600",
    memory:  "text-blue-500",
    disk:    "text-blue-500",
    fetched: "text-green-600",
    error:   "text-red-500",
    empty:  "text-gray-400",
  };

  return (
    <Card title="4. Download NOAA Data">
      <button onClick={() => setStage("years")} className="text-xs text-blue-600 hover:underline mb-3 block">
        ← Change years
      </button>

      {!running && !done && (
        <>
          <p className="text-sm text-gray-500 mb-4">
            Ready to download {selectedYears.length} year(s) from NOAA for station{" "}
            <span className="font-mono font-medium">{selectedStation}</span>.
          </p>
          <button
            onClick={handleFetch}
            className="w-full text-white font-medium py-2 px-4 rounded-lg text-sm transition-all"
            style={{
              background: "#4f8ef7",
              boxShadow: "0 0 0 2px #4f8ef755, 0 4px 14px #4f8ef740",
              transform: "translateY(-1px)",
              border: "none",
            }}
          >
            ⬇ Start Download
          </button>
        </>
      )}

      {(running || done) && (
        <>
          {/* Progress bar */}
          <div className="mb-3">
            <div className="flex justify-between text-xs text-gray-500 mb-1">
              <span>{done ? "Complete" : "Downloading…"}</span>
              <span>{pct}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div
                className={`h-2 rounded-full transition-all duration-300 ${done ? "bg-green-500" : "bg-blue-500"}`}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>

          {/* Year rows */}
          <div className="space-y-1 max-h-64 overflow-y-auto mb-3">
            {[...rows].sort((a, b) => a.year - b.year).map((r) => (
              <div key={r.year} className="flex justify-between text-xs py-0.5">
                <span className="font-mono text-gray-700">{r.year}</span>
                <span className={STATUS_COLOR[r.status] ?? "text-gray-500"}>
                  {r.rows > 0 ? `${r.rows.toLocaleString()} rows · ` : ""}
                  {STATUS_LABEL[r.status] ?? r.status}
                </span>
              </div>
            ))}
          </div>

          {/* Open-Meteo ERA5 status row */}
          {omStatus !== "idle" && (
            <div className={`flex justify-between text-xs py-1.5 px-2 rounded mb-3 ${
              omStatus === "error" ? "bg-red-950 border border-red-800" :
              omStatus === "done"  ? "bg-green-950 border border-green-800" :
                                     "bg-blue-950 border border-blue-800"
            }`}>
              <span className="text-gray-400">🌐 Open-Meteo ERA5</span>
              {omStatus === "loading" && (
                <span className="text-blue-400 animate-pulse">
                  fetching {selectedYears.length > 0 ? `${Math.min(...selectedYears)}–${Math.max(...selectedYears)}` : ""}…
                </span>
              )}
              {omStatus === "done" && (
                <span className="text-green-400">✓ ready</span>
              )}
              {omStatus === "error" && (
                <span className="text-red-400 text-right break-all">
                  ✗ {omErrMsg}
                </span>
              )}
            </div>
          )}
        </>
      )}

      {error && <p className="text-red-500 text-sm mt-2">{error}</p>}

      {done && token && (
        <div className="space-y-2">
          <button
            onClick={() => downloadCsv(token, selectedStation ?? "station")}
            className="wa-btn wa-btn-outline"
            style={{
              width: "100%",
              border: "1px solid #4f8ef7",
              color: "#4f8ef7",
              background: "transparent",
            }}
          >
            ⬇ Download merged CSV
          </button>
          <button
            onClick={() => advanceTo("filter")}
            className="wa-btn wa-btn-success"
            style={{
              background: "#22c55e",
              boxShadow: "0 0 0 2px #22c55e55, 0 4px 14px #22c55e40",
              transform: "translateY(-1px)",
            }}
          >
            ✓ Run Analysis →
          </button>
        </div>
      )}
    </Card>
  );
}



