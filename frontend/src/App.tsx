import { Fragment, useEffect, useState } from "react";
import "./App.css";
import { useStore } from "./store";
import type { AppState } from "./store";
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

function getSuggestions(stage: StageName, s: AppState): string[] {
  const sfx = s.units === "C" ? "°C" : "°F";
  switch (stage) {
    case "site":
      return [
        "How does elevation affect pressure?",
        "What coordinates format do you accept?",
      ];
    case "station": {
      const sel = s.noaaStations.find((n) => n.GHCN_ID === s.selectedStation);
      const dist = sel?.dist_miles != null ? `${sel.dist_miles.toFixed(1)} mi away` : null;
      return [
        sel ? `Why is ${sel.NAME} recommended?` : "Why prefer closer stations?",
        dist ? `Is ${dist} too far for reliable data?` : "What distance is too far for a station?",
        "How are ASHRAE reference stations selected?",
      ];
    }
    case "years": {
      const n = s.selectedYears.length;
      return [
        n > 0 ? `Is ${n} years of data enough for design conditions?` : "How many years should I select?",
        "Why are some years greyed out?",
        "Does more historical data always improve accuracy?",
      ];
    }
    case "fetch":
      return [
        "What measurements does NOAA ISD provide?",
        "Why might a year have fewer rows than expected?",
        "What is the difference between NOAA and ERA5?",
      ];
    case "filter": {
      const f = s.selectedFilter;
      return [
        f ? `What is the "${f}" filter and when should I use it?` : "What is the FM-15 filter?",
        "Which filter gives the most conservative design conditions?",
        "What do NOAA quality codes 2 and 3 mean?",
      ];
    }
    case "results": {
      const dc = s.processResult?.design_conditions as Record<string, unknown> | undefined;
      const stats = (dc?.Stats ?? []) as Record<string, unknown>[];
      const row1 = stats.find((r) => Number(r["%"]) === 1);
      const dbCol = s.units === "C" ? "DB_C" : "DB_F";
      const tdb = row1 ? Number(row1[dbCol]) : null;
      const station = s.processResult?.meta.station_name ?? null;
      return [
        tdb != null ? `Why is the 1% dry bulb ${tdb.toFixed(1)}${sfx} — is that typical?` : "Explain 1% exceedance",
        station ? `How reliable is ${station} for this analysis?` : "Why is ASHRAE different from NOAA?",
        "What is MCWB and how does it affect chiller sizing?",
        "Explain the no-freeze winterization window",
      ];
    }
    default:
      return [];
  }
}

// Suggestion chips shown in the right canvas above the active stage.
// Clicking sends the question directly to the chat panel via the store.
function CanvasSuggestions({ stage }: { stage: StageName }) {
  const store = useStore();
  const { setPendingChatMessage } = store;
  const chips = getSuggestions(stage, store);
  if (chips.length === 0) return null;
  return (
    <div style={{
      display: "flex", flexWrap: "wrap", gap: "6px",
      padding: "8px 0 4px", alignItems: "center",
    }}>
      <span style={{ fontSize: "10px", color: "var(--wa-text-muted)", whiteSpace: "nowrap", marginRight: "2px" }}>
        💬
      </span>
      {chips.map((q) => (
        <button
          key={q}
          onClick={() => setPendingChatMessage(q)}
          style={{
            background: "var(--wa-surface)",
            border: "1px solid var(--wa-border)",
            borderRadius: "12px",
            padding: "3px 10px",
            fontSize: "11px",
            color: "var(--wa-text-dim)",
            cursor: "pointer",
            transition: "border-color 0.15s, color 0.15s",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--wa-accent)"; e.currentTarget.style.color = "var(--wa-accent)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--wa-border)"; e.currentTarget.style.color = "var(--wa-text-dim)"; }}
        >
          {q}
        </button>
      ))}
    </div>
  );
}

const STAGE_LABELS: Partial<Record<StageName, string>> = {
  station: "Select Station",
  years:   "Select Years",
  fetch:   "Download Data",
  filter:  "Filter & Process",
  results: "Results",
};

// ── Main app ──────────────────────────────────────────────────

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api";

export default function App() {
  const appStore = useStore();
  const {
    stage, units, setUnits, reset,
    lat, selectedStation, selectedYears, fetchToken, selectedFilter, processResult,
  } = appStore;

  const [userEmail, setUserEmail] = useState<string>("");

  useEffect(() => {
    fetch(`${BASE}/auth/me`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.email) {
          setUserEmail(data.email);
        } else if (import.meta.env.PROD) {
          window.location.href = `${BASE}/auth/login`;
        } else {
          setUserEmail("dev@local");
        }
      })
      .catch(() => {
        if (import.meta.env.PROD) window.location.href = `${BASE}/auth/login`;
        else setUserEmail("dev@local");
      });
  }, []);

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
          {userEmail && userEmail !== "dev@local" && (
            <>
              <span style={{ fontSize: "11px", color: "var(--wa-text-dim)", maxWidth: "160px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {userEmail}
              </span>
              <a
                href={`${BASE}/auth/logout`}
                style={{
                  padding: "4px 10px", borderRadius: "6px",
                  border: "1px solid var(--wa-border)", fontSize: "12px",
                  background: "transparent", color: "var(--wa-text-dim)", cursor: "pointer",
                  textDecoration: "none",
                }}
              >
                Sign out
              </a>
            </>
          )}
        </div>
      </header>

      {/* Two-panel body */}
      <div className="wa-panels">
        <div className="wa-chat">
          <ChatPanel suggestions={getSuggestions(stage, appStore)} />
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
                    <CanvasSuggestions stage={s} />
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

      {/* Footer */}
      <footer style={{
        textAlign: "center", padding: "10px 16px",
        fontSize: "11px", color: "var(--wa-text-dim)",
        borderTop: "1px solid var(--wa-border)",
        background: "var(--wa-bg)",
      }}>
        NOAA Weather Analysis Tool &nbsp;·&nbsp; For help contact&nbsp;
        <a href="mailto:nsujeet@gmail.com" style={{ color: "var(--wa-accent)", textDecoration: "none" }}>
          nsujeet@gmail.com
        </a>
      </footer>
    </div>
  );
}
