/**
 * ProcessStage — trigger /process, wait, advance
 */
import { useState } from "react";
import { useStore } from "../store";
import { processData } from "../api";
import Card from "../components/Card";

export default function ProcessStage() {
  const { lat, lon, siteInfo, selectedStation, selectedYears, units,
    fetchToken, setProcessResult, advanceTo } = useStore();

  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  const handleProcess = async () => {
    if (!fetchToken || !selectedStation || lat == null || lon == null) return;
    setLoading(true);
    setError(null);
    try {
      const result = await processData(fetchToken, {
        station_id: selectedStation,
        years: selectedYears,
        units,
        lat,
        lon,
        elevation_m: siteInfo?.elevation_m ?? 0,
      });
      setProcessResult(result);
      advanceTo("results");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Processing failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card title="5. Process Data">
      <p className="text-sm text-gray-500 mb-4">
        Merge years → clean & filter → compute psychrometrics → derive design conditions.
      </p>

      {error && <p className="text-red-500 text-sm mb-3">{error}</p>}

      <button
        onClick={handleProcess}
        disabled={loading}
        className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium py-2 px-4 rounded-lg text-sm transition-colors"
      >
        {loading ? "Processing…" : "Run →"}
      </button>
    </Card>
  );
}
