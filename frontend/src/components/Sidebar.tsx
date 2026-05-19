import { useStore } from "../store";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-xs py-1 border-b border-gray-100 last:border-0">
      <span className="text-gray-400">{label}</span>
      <span className="font-medium text-gray-700 text-right max-w-[60%] truncate">{value}</span>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">{title}</p>
      {children}
    </div>
  );
}

const STAGE_LABELS: Record<string, string> = {
  site:    "Site confirmed",
  station: "Station selected",
  years:   "Years selected",
  fetch:   "Data downloaded",
  filter:  "Filter & run",
  results: "Results ready",
};

export default function Sidebar() {
  const { stage, units, lat, lon, siteInfo, selectedStation,
    noaaStations, selectedYears, processResult } = useStore();

  const stages = Object.keys(STAGE_LABELS);
  const currentIdx = stages.indexOf(stage);
  const sfx = units === "C" ? "°C" : "°F";
  const pUnit = units === "C" ? "kPa" : "psia";

  const stationName = noaaStations.find((s) => s.GHCN_ID === selectedStation)?.NAME ?? selectedStation;

  const pr = processResult;
  const dc = pr?.design_conditions as Record<string, unknown> | undefined;
  const stats = dc?.Stats as Record<string, unknown>[] | undefined;
  const stat1 = stats?.find((r) => r["%"] === 1 || r["%"] === "1");

  return (
    <aside className="w-56 shrink-0 bg-white border-r border-gray-200 h-[calc(100vh-88px)] sticky top-[88px] overflow-y-auto px-3 py-4 hidden lg:block">
      <p className="text-sm font-semibold text-gray-700 mb-4">Summary</p>

      {/* Progress */}
      <Section title="Progress">
        {stages.map((s, i) => {
          const done = i < currentIdx;
          const active = i === currentIdx;
          return (
            <div key={s} className="flex items-center gap-1.5 py-0.5">
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                done ? "bg-green-500" : active ? "bg-blue-500" : "bg-gray-200"
              }`} />
              <span className={`text-xs ${active ? "text-blue-600 font-medium" : done ? "text-gray-500" : "text-gray-300"}`}>
                {STAGE_LABELS[s]}
              </span>
            </div>
          );
        })}
      </Section>

      {/* Site */}
      {lat != null && (
        <Section title="Site">
          <Row label="Lat / Lon" value={`${lat.toFixed(4)}, ${lon!.toFixed(4)}`} />
          {siteInfo && (
            <>
              <Row label="Elevation" value={`${siteInfo.elevation_ft.toFixed(0)} ft`} />
              <Row label="Pressure" value={
                units === "C"
                  ? `${siteInfo.pressure_kpa.toFixed(3)} ${pUnit}`
                  : `${siteInfo.pressure_psi.toFixed(3)} ${pUnit}`
              } />
              <Row label="Timezone" value={siteInfo.timezone} />
            </>
          )}
        </Section>
      )}

      {/* Station */}
      {selectedStation && (
        <Section title="Station">
          <Row label="ID" value={selectedStation} />
          {stationName && stationName !== selectedStation && (
            <Row label="Name" value={stationName} />
          )}
          {pr?.meta && (
            <>
              <Row label="Distance" value={`${pr.meta.distance_miles.toFixed(1)} mi`} />
              <Row label="Elev delta" value={`${pr.meta.elevation_delta_ft.toFixed(0)} ft`} />
            </>
          )}
        </Section>
      )}

      {/* Years */}
      {selectedYears.length > 0 && (
        <Section title="Years">
          <Row label="Selected" value={`${selectedYears.length} yrs`} />
          <Row label="Range" value={`${Math.min(...selectedYears)}–${Math.max(...selectedYears)}`} />
        </Section>
      )}

      {/* Results */}
      {pr && (
        <Section title="Design Conditions">
          <Row label="Filter" value={pr.filter_used} />
          <Row label="Rows" value={pr.n_rows.toLocaleString()} />
          {stat1 && (
            <>
              <Row label={`1% Tdb`} value={`${stat1[`DB_${units === "C" ? "C" : "F"}`] ?? "—"} ${sfx}`} />
              <Row label={`1% Twb`} value={`${stat1[`WB_${units === "C" ? "C" : "F"}`] ?? "—"} ${sfx}`} />
            </>
          )}
        </Section>
      )}
    </aside>
  );
}
