import { Fragment } from "react";
import "./App.css";
import { useStore } from "./store";
import ChatPanel from "./components/ChatPanel";
import SiteStage from "./stages/SiteStage";
import StationStage from "./stages/StationStage";
import YearsStage from "./stages/YearsStage";
import FetchStage from "./stages/FetchStage";
import FilterStage from "./stages/FilterStage";
import ResultsStage from "./stages/ResultsStage";

const STAGES = ["site", "station", "years", "fetch", "filter", "results"] as const;
type StageName = typeof STAGES[number];

// ── Completed step summary cards ──────────────────────────────

function StepDone({ label, summary, onRewind }: { label: string; summary: string; onRewind: () => void }) {
  return (
    <div className="wa-step-done">
      <div className="wa-step-done-meta">
        <div className="wa-step-done-label">{label}</div>
        <div className="wa-step-done-summary">{summary}</div>
      </div>
      <button className="wa-rewind-btn" onClick={onRewind}>← Change</button>
    </div>
  );
}

function SiteDoneCard() {
  const { lat, lon, siteInfo, units, omResult, omLoading, omError, setStage } = useStore();
  if (lat == null) return null;
  const pUnit = units === "C" ? "kPa" : "psia";
  const elev = siteInfo ? `${siteInfo.elevation_ft.toFixed(0)} ft` : "";
  const pres = siteInfo
    ? `${(units === "C" ? siteInfo.pressure_kpa : siteInfo.pressure_psi).toFixed(3)} ${pUnit}`
    : "";
  return (
    <div>
      <StepDone
        label="Site"
        summary={[`${lat.toFixed(4)}°, ${lon!.toFixed(4)}°`, elev, pres].filter(Boolean).join(" · ")}
        onRewind={() => setStage("site")}
      />
      {omLoading && !omResult && (
        <div className="text-xs px-3 py-1 text-blue-400 animate-pulse">
          🌐 Fetching ERA5 weather data…
        </div>
      )}
      {omError && !omResult && (
        <div className="text-xs px-3 py-1 text-orange-400" title={omError}>
          🌐 ERA5 unavailable: {omError}
        </div>
      )}
      {omResult && (
        <div className="text-xs px-3 py-1 text-green-500">
          🌐 ERA5 ready
        </div>
      )}
    </div>
  );
}

function StationDoneCard() {
  const { selectedStation, noaaStations, setStage } = useStore();
  if (!selectedStation) return null;
  const name = noaaStations.find((s) => s.GHCN_ID === selectedStation)?.NAME;
  const dist = noaaStations.find((s) => s.GHCN_ID === selectedStation)?.dist_miles;
  return (
    <StepDone
      label="Station"
      summary={[selectedStation, name, dist != null ? `${dist.toFixed(1)} mi` : ""].filter(Boolean).join(" · ")}
      onRewind={() => setStage("station")}
    />
  );
}

function YearsDoneCard() {
  const { selectedYears, setStage } = useStore();
  if (selectedYears.length === 0) return null;
  const range = selectedYears.length > 1
    ? `${Math.min(...selectedYears)}–${Math.max(...selectedYears)}`
    : String(selectedYears[0]);
  return (
    <StepDone
      label="Years"
      summary={`${range} · ${selectedYears.length} year${selectedYears.length !== 1 ? "s" : ""}`}
      onRewind={() => setStage("years")}
    />
  );
}

function FetchDoneCard() {
  const { fetchToken, selectedYears, setStage } = useStore();
  if (!fetchToken) return null;
  const range = selectedYears.length > 1
    ? `${Math.min(...selectedYears)}–${Math.max(...selectedYears)}`
    : selectedYears.length === 1 ? String(selectedYears[0]) : "";
  return (
    <StepDone
      label="Download"
      summary={[range, `${selectedYears.length} year${selectedYears.length !== 1 ? "s" : ""} downloaded`].filter(Boolean).join(" · ")}
      onRewind={() => setStage("fetch")}
    />
  );
}

function FilterDoneCard() {
  const { selectedFilter, filterScores, setStage } = useStore();
  if (!selectedFilter) return null;
  const score = filterScores?.find((f) => f.name === selectedFilter);
  const detail = score
    ? `${score.coverage_pct}% coverage · ${score.rows.toLocaleString()} rows`
    : "";
  return (
    <StepDone
      label="Filter"
      summary={[selectedFilter, detail].filter(Boolean).join(" · ")}
      onRewind={() => setStage("filter")}
    />
  );
}

// ── Stage suggestions for chat ────────────────────────────────

function getSuggestions(stage: StageName): string[] {
  switch (stage) {
    case "site":    return ["How does elevation affect pressure?", "What coordinates format do you use?"];
    case "station": return ["Why prefer closer stations?", "What does the recommendation color mean?", "How are ASHRAE stations selected?"];
    case "years":   return ["How many years should I select?", "Why are some years unavailable?"];
    case "fetch":   return ["What data does NOAA provide?", "Why might a year have fewer rows?"];
    case "filter":  return ["What is FM-15 filter?", "Which filter should I pick?", "What do quality codes mean?"];
    case "results": return ["Explain 1% exceedance", "Why is ASHRAE different from NOAA?", "What is MCWB?", "Explain the winterization window"];
    default:        return [];
  }
}

const STAGE_LABELS: Partial<Record<StageName, string>> = {
  station: "Select Station",
  years:   "Select Years",
  fetch:   "Download Data",
  filter:  "Filter & Process",
  results: "Results",
};

// ── Main app ──────────────────────────────────────────────────

export default function App() {
  const {
    stage, units, setUnits, reset,
    lat, selectedStation, selectedYears, fetchToken, selectedFilter, processResult,
  } = useStore();

  const stageIdx = STAGES.indexOf(stage);

  // A step shows as a done card when it has data AND is not the currently active stage.
  // This preserves subsequent steps when the user navigates backward.
  const hasData: Record<StageName, boolean> = {
    site:    lat != null,
    station: !!selectedStation,
    years:   selectedYears.length > 0,
    fetch:   !!fetchToken,
    filter:  !!selectedFilter,
    results: !!processResult,
  };

  const doneCard: Partial<Record<StageName, JSX.Element>> = {
    site:    <SiteDoneCard />,
    station: <StationDoneCard />,
    years:   <YearsDoneCard />,
    fetch:   <FetchDoneCard />,
    filter:  <FilterDoneCard />,
  };

  return (
    <div className="wa-app">
      {/* Header */}
      <header className="wa-header">
        <span className="wa-logo">Weather Analysis</span>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {(["F", "C"] as const).map((u) => (
            <button
              key={u}
              onClick={() => setUnits(u)}
              style={{
                padding: "4px 12px", borderRadius: "20px", border: "1px solid",
                fontSize: "12px", fontWeight: 600, cursor: "pointer",
                background: units === u ? "var(--wa-accent)" : "transparent",
                borderColor: units === u ? "var(--wa-accent)" : "var(--wa-border)",
                color: units === u ? "#fff" : "var(--wa-text-dim)",
                transition: "all 0.15s",
              }}
            >
              °{u}
            </button>
          ))}
          <button
            onClick={reset}
            style={{
              padding: "4px 12px", borderRadius: "6px",
              border: "1px solid var(--wa-border)", fontSize: "12px",
              background: "transparent", color: "var(--wa-text-dim)", cursor: "pointer",
            }}
          >
            New analysis
          </button>
        </div>
      </header>

      {/* Two-panel body */}
      <div className="wa-panels">
        <div className="wa-chat">
          <ChatPanel suggestions={getSuggestions(stage)} />
        </div>

        <div className="wa-canvas">
          <div className="wa-canvas-scroll">
            {/* Render each stage in order:
                - active stage gets the full component (with divider above it)
                - all other stages with data get a compact done card
                This preserves downstream done cards when navigating backward */}
            {STAGES.map((s) => {
              if (s === stage) {
                return (
                  <Fragment key={s}>
                    {stageIdx > 0 && (
                      <div className="wa-stage-divider">{STAGE_LABELS[s] ?? ""}</div>
                    )}
                    {s === "site"    && <SiteStage />}
                    {s === "station" && <StationStage />}
                    {s === "years"   && <YearsStage />}
                    {s === "fetch"   && <FetchStage />}
                    {s === "filter"  && <FilterStage />}
                    {s === "results" && <ResultsStage />}
                  </Fragment>
                );
              }
              if (!hasData[s]) return null;
              return <Fragment key={s}>{doneCard[s] ?? null}</Fragment>;
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
