/**
 * SiteStage — location search + lat/lon entry + site confirmation.
 */
import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { geocode, confirmSite, getOpenMeteo } from "../api";
import Card from "../components/Card";

interface GeoResult { display_name: string; lat: number; lon: number; }

export default function SiteStage() {
  const {
    units, setSite, advanceTo, setStage,
    setOmResult, setOmLoading, setOmError,
    lat: storedLat, lon: storedLon,
  } = useStore();
  const [lat, setLat] = useState(storedLat != null ? storedLat.toFixed(6) : "");
  const [lon, setLon] = useState(storedLon != null ? storedLon.toFixed(6) : "");
  const [query,      setQuery]      = useState("");
  const [results,    setResults]    = useState<GeoResult[]>([]);
  const [searching,  setSearching]  = useState(false);
  const [showDrop,   setShowDrop]   = useState(false);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState<string | null>(null);
  const debounce     = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dropRef      = useRef<HTMLDivElement>(null);

  // Debounced geocode search
  useEffect(() => {
    if (debounce.current) clearTimeout(debounce.current);
    if (query.trim().length < 3) { setResults([]); setShowDrop(false); return; }
    debounce.current = setTimeout(async () => {
      setSearching(true);
      try {
        const r = await geocode(query);
        setResults(r.results);
        setShowDrop(r.results.length > 0);
      } catch { setResults([]); }
      finally { setSearching(false); }
    }, 400);
  }, [query]);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) setShowDrop(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const pickResult = (r: GeoResult) => {
    setLat(r.lat.toFixed(6));
    setLon(r.lon.toFixed(6));
    setQuery(r.display_name.split(",").slice(0, 3).join(","));
    setShowDrop(false);
  };

  const handleConfirm = async () => {
    const latN = parseFloat(lat);
    const lonN = parseFloat(lon);
    if (isNaN(latN) || isNaN(lonN)) { setError("Enter valid latitude and longitude."); return; }
    setLoading(true); setError(null);
    try {
      const info = await confirmSite(latN, lonN, units);
      setSite(latN, lonN, info);

      // Fire OM immediately on site confirm — last 15 years, same as Streamlit
      const omEnd   = new Date().getFullYear() - 1;
      const omStart = omEnd - 14;
      setOmLoading(true);
      setOmError(null);
      getOpenMeteo(latN, lonN, omStart, omEnd, units)
        .then((r) => { setOmResult(r); setOmLoading(false); })
        .catch((e: unknown) => {
          const err = e as { response?: { data?: { error?: string } }; message?: string };
          setOmError(err?.response?.data?.error ?? err?.message ?? "Open-Meteo failed");
          setOmLoading(false);
        });

      advanceTo("station");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to confirm site.");
    } finally { setLoading(false); }
  };

  const inputStyle = {
    background: "var(--wa-bg)", border: "1px solid var(--wa-border)",
    color: "var(--wa-text)", borderRadius: "8px", padding: "8px 12px",
    fontSize: "13px", width: "100%", outline: "none", boxSizing: "border-box" as const,
  };

  return (
    <Card title="1. Site Location">
      {/* Location search */}
      <div className="mb-4 relative" ref={dropRef}>
        <label style={{ display: "block", fontSize: "11px", fontWeight: 600, color: "var(--wa-text-dim)", marginBottom: "4px" }}>Search location</label>
        <div className="relative">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => results.length > 0 && setShowDrop(true)}
            placeholder="e.g. El Paso TX, or Phoenix AZ"
            style={{ ...inputStyle, paddingRight: "32px" }}
          />
          {searching && (
            <span className="absolute right-2 top-2 text-xs text-gray-400 animate-pulse">…</span>
          )}
        </div>
        {showDrop && (
          <div className="absolute z-20 w-full rounded-lg shadow-lg mt-1 max-h-48 overflow-y-auto" style={{ background: "var(--wa-surface)", border: "1px solid var(--wa-border)" }}>
            {results.map((r, i) => (
              <button
                key={i}
                onClick={() => pickResult(r)}
                className="w-full text-left px-3 py-2 text-xs border-b last:border-0"
                style={{ color: "var(--wa-text)", borderColor: "var(--wa-border)", background: "transparent", wordBreak: "break-word", overflowWrap: "break-word" }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--wa-accent-dim)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                {r.display_name}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Manual lat/lon */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <label style={{ display: "block", fontSize: "11px", fontWeight: 600, color: "var(--wa-text-dim)", marginBottom: "4px" }}>Latitude</label>
          <input type="number" step="any" value={lat} onChange={(e) => setLat(e.target.value)}
            placeholder="e.g. 33.4484" style={inputStyle} />
        </div>
        <div>
          <label style={{ display: "block", fontSize: "11px", fontWeight: 600, color: "var(--wa-text-dim)", marginBottom: "4px" }}>Longitude</label>
          <input type="number" step="any" value={lon} onChange={(e) => setLon(e.target.value)}
            placeholder="e.g. -112.0740" style={inputStyle} />
        </div>
      </div>

      {error && <p style={{ color: "#ff6b6b", fontSize: "13px", marginBottom: "10px" }}>{error}</p>}

      <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
        <button
          onClick={handleConfirm}
          disabled={loading}
          className="wa-btn wa-btn-primary"
        >
          {loading ? "Looking up site…" : "✓ Confirm Site →"}
        </button>
        {storedLat != null && (
          <button
            onClick={() => setStage("station")}
            style={{
              padding: "6px 14px", borderRadius: "6px", fontSize: "12px",
              background: "transparent", border: "1px solid var(--wa-border)",
              color: "var(--wa-text-dim)", cursor: "pointer",
            }}
          >
            ← Keep current
          </button>
        )}
      </div>
    </Card>
  );
}
