/**
 * store.ts — global app state via Zustand
 */
import { create } from "zustand";
import type { SiteInfo, NoaaStation, AshraStation, ProcessResult, OmResult, FilterScore, AshraConditionResult } from "./api";

export type Stage = "site" | "station" | "years" | "fetch" | "filter" | "results";

export interface AppState {
  // Step 0
  units: "F" | "C";
  setUnits: (u: "F" | "C") => void;

  // Stage 1 — site
  lat: number | null;
  lon: number | null;
  siteInfo: SiteInfo | null;
  setSite: (lat: number, lon: number, info: SiteInfo) => void;

  // Stage 1 — stations
  noaaStations: NoaaStation[];
  ashraStations: AshraStation[];
  selectedStation: string | null;
  recommendedStationId: string | null;
  ashraConditions: AshraConditionResult[];
  setStations: (noaa: NoaaStation[], ashra: AshraStation[], recommended: string | null) => void;
  selectStation: (id: string) => void;
  setAshraConditions: (c: AshraConditionResult[]) => void;

  // Availability cache from bulk check (station_id → available years)
  stationAvailMap: Record<string, number[]>;
  setStationAvailMap: (m: Record<string, number[]>) => void;

  // Stage 1 — years
  availableYears: number[];
  selectedYears: number[];
  setAvailableYears: (years: number[]) => void;
  toggleYear: (year: number) => void;
  setSelectedYears: (years: number[]) => void;

  // Stage 1 — fetch
  fetchToken: string | null;
  fetchProgress: { i: number; total: number; year: number; pct: number; status: string } | null;
  cachedYears: number[];
  setFetchToken: (token: string) => void;
  setFetchProgress: (p: AppState["fetchProgress"]) => void;
  setCachedYears: (years: number[]) => void;

  // Open-Meteo (auto-fetched after site confirm)
  omResult: OmResult | null;
  omLoading: boolean;
  omError: string | null;
  setOmResult: (r: OmResult | null) => void;
  setOmLoading: (v: boolean) => void;
  setOmError: (e: string | null) => void;

  // ASHRAE edition + level (persisted so navigation doesn't reset them)
  ashraEdition: string;
  ashraLevel: "0.4" | "1" | "2";
  setAshraEdition: (e: string) => void;
  setAshraLevel: (l: "0.4" | "1" | "2") => void;

  // Filter stage
  filterScores: FilterScore[] | null;
  selectedFilter: string | null;
  excludeQualityCodes: string[];
  clipLower: number;
  clipUpper: number | null;
  clipLowerDew: number;
  clipUpperDew: number | null;
  setFilterScores: (f: FilterScore[] | null) => void;
  setSelectedFilter: (f: string) => void;
  setExcludeQualityCodes: (codes: string[]) => void;
  setClipLower: (v: number) => void;
  setClipUpper: (v: number | null) => void;
  setClipLowerDew: (v: number) => void;
  setClipUpperDew: (v: number | null) => void;

  // Process result
  processResult: ProcessResult | null;
  setProcessResult: (r: ProcessResult) => void;

  // Navigation
  stage: Stage;
  setStage: (s: Stage) => void;
  advanceTo: (s: Stage) => void;

  // Proactive chat injection — canvas chips write here, ChatPanel consumes it
  pendingChatMessage: string | null;
  setPendingChatMessage: (msg: string | null) => void;

  // Reset
  reset: () => void;
}

const initial = {
  units: "F" as const,
  lat: null,
  lon: null,
  siteInfo: null,
  omResult: null,
  omLoading: false,
  omError: null,
  noaaStations: [],
  ashraStations: [],
  selectedStation: null,
  recommendedStationId: null,
  ashraConditions: [],
  stationAvailMap: {} as Record<string, number[]>,
  availableYears: [],
  selectedYears: [],
  fetchToken: null,
  fetchProgress: null,
  cachedYears: [],
  ashraEdition: "2025",
  ashraLevel: "1" as "0.4" | "1" | "2",
  filterScores: null,
  selectedFilter: null,
  excludeQualityCodes: ["2", "3"],
  clipLower: 5.0,
  clipUpper: null,
  clipLowerDew: 5.0,
  clipUpperDew: null,
  processResult: null,
  stage: "site" as Stage,
  pendingChatMessage: null,
};

export const useStore = create<AppState>((set, get) => ({
  ...initial,

  setUnits: (u) => set({ units: u }),

  setSite: (lat, lon, info) => set({
    lat, lon, siteInfo: info,
    // Clear downstream so StationStage refetches for the new location
    noaaStations: [], ashraStations: [], selectedStation: null,
    recommendedStationId: null, ashraConditions: [],
    stationAvailMap: {}, availableYears: [],
    omResult: null,  // ERA5 re-fetched in SiteStage.handleConfirm after this
  }),

  setStations: (noaa, ashra, recommended) =>
    set({
      noaaStations: noaa,
      ashraStations: ashra,
      selectedStation: recommended ?? (noaa[0]?.GHCN_ID ?? null),
      recommendedStationId: recommended,
    }),

  setStationAvailMap: (m) => set({ stationAvailMap: m }),
  selectStation: (id) => set({ selectedStation: id }),
  setAshraConditions: (c) => set({ ashraConditions: c }),

  setAvailableYears: (years) => {
    const lastFullYear = new Date().getFullYear() - 1;
    const sorted = [...years].filter((y) => y <= lastFullYear).sort((a, b) => a - b);
    const last10 = sorted.slice(-10);
    set({ availableYears: years, selectedYears: last10 });
  },

  toggleYear: (year) => {
    const sel = get().selectedYears;
    set({
      selectedYears: sel.includes(year) ? sel.filter((y) => y !== year) : [...sel, year].sort(),
    });
  },

  setSelectedYears: (years) => set({ selectedYears: years }),

  setFetchToken: (token) => set({ fetchToken: token }),
  setFetchProgress: (p) => set({ fetchProgress: p }),
  setCachedYears: (years) => set({ cachedYears: years }),

  setOmResult: (r) => set({ omResult: r }),
  setOmLoading: (v) => set({ omLoading: v }),
  setOmError: (e) => set({ omError: e }),

  setAshraEdition: (e) => set({ ashraEdition: e }),
  setAshraLevel: (l) => set({ ashraLevel: l }),

  setFilterScores: (f) => set({ filterScores: f }),
  setSelectedFilter: (f) => set({ selectedFilter: f }),
  setExcludeQualityCodes: (codes) => set({ excludeQualityCodes: codes }),
  setClipLower: (v) => set({ clipLower: v }),
  setClipUpper: (v) => set({ clipUpper: v }),
  setClipLowerDew: (v) => set({ clipLowerDew: v }),
  setClipUpperDew: (v) => set({ clipUpperDew: v }),

  setProcessResult: (r) => set({ processResult: r }),

  setStage: (s) => set({ stage: s }),
  advanceTo: (s) => set({ stage: s }),

  setPendingChatMessage: (msg) => set({ pendingChatMessage: msg }),

  reset: () => set(initial),
}));
