/**
 * YearsStage — pick which years to download
 */
import { useEffect, useState } from "react";
import { useStore } from "../store";
import { checkAvailability } from "../api";
import Card from "../components/Card";

const ALL_YEARS = Array.from({ length: 26 }, (_, i) => 2000 + i); // 2000â€“2025

export default function YearsStage() {
  const { selectedStation, availableYears, selectedYears, cachedYears,
    setAvailableYears, toggleYear, setSelectedYears, advanceTo, setStage } = useStore();

  const [loading, setLoading] = useState(false);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    // Skip if already checked this session OR if we already have availability data
    if (checked || !selectedStation || availableYears.length > 0) return;
    setLoading(true);
    checkAvailability(selectedStation)
      .then((r) => { setAvailableYears(r.available_years); setChecked(true); })
      .finally(() => setLoading(false));
  }, [selectedStation]);

  const avail  = new Set(availableYears);
  const sel    = new Set(selectedYears);
  const cached = new Set(cachedYears);

  const selectAll  = () => setSelectedYears(availableYears.filter((y) => y >= 2000));
  const selectLast10 = () => setSelectedYears(availableYears.filter((y) => y >= 2015));
  const clearAll   = () => setSelectedYears([]);

  return (
    <Card title="3. Select Years">
      <button onClick={() => setStage("station")} className="text-xs text-blue-600 hover:underline mb-3 block">
        ← Change station
      </button>
      <p className="text-xs text-gray-400 mb-3">
        {loading ? "Checking NOAA availability…" :
          `${selectedYears.length} selected · ${cachedYears.length} in memory · ${availableYears.length} available on NOAA`}
        {" · "}✓ = in memory · × = no data
      </p>

      {/* Quick-select buttons */}
      <div className="flex gap-2 mb-3">
        {[
          { label: "Last 10", action: selectLast10 },
          { label: "All",     action: selectAll },
          { label: "Clear",   action: clearAll },
        ].map(({ label, action }) => (
          <button
            key={label}
            onClick={action}
            className="text-xs px-3 py-1 rounded border border-[#2e3148] hover:border-[#4f8ef7] text-[#8b90a8] hover:text-[#4f8ef7] transition-colors bg-transparent"
          >
            {label}
          </button>
        ))}
        <span className="text-xs text-gray-400 self-center ml-auto">
          {selectedYears.length} selected
        </span>
      </div>

      {/* Year grid */}
      <div className="grid grid-cols-13 gap-1 mb-4" style={{ gridTemplateColumns: "repeat(13, minmax(0, 1fr))" }}>
        {ALL_YEARS.map((yr) => {
          const isAvail = avail.has(yr);
          const isSel   = sel.has(yr);
          return (
            <button
              key={yr}
              onClick={() => isAvail && toggleYear(yr)}
              disabled={!isAvail}
              className={`text-xs py-1 rounded font-mono transition-colors ${
                !isAvail
                  ? "bg-[#0f1117] text-[#3e4160] cursor-not-allowed"
                  : isSel
                  ? "bg-[#4f8ef7] text-white"
                  : "bg-[#1a1d27] border border-[#2e3148] text-[#8b90a8] hover:border-[#4f8ef7]"
              }`}
            >
              {loading ? "…" : !isAvail ? `×${yr}` : cached.has(yr) ? `✓${yr}` : `${yr}`}
            </button>
          );
        })}
      </div>

      <button
        onClick={() => advanceTo("fetch")}
        disabled={selectedYears.length === 0}
        className="wa-btn wa-btn-primary"
      >
        {selectedYears.length > 0
          ? `✓ Fetch ${selectedYears.length} year${selectedYears.length !== 1 ? "s" : ""} →`
          : "Select years to continue"}
      </button>
    </Card>
  );
}

