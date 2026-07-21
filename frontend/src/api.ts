/**
 * api.ts — typed wrappers for every backend endpoint
 */
import axios from "axios";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api";
const http = axios.create({ baseURL: BASE });

export interface SiteInfo {
  elevation_m: number;
  elevation_ft: number;
  pressure_psi: number;
  pressure_kpa: number;
  timezone: string;
  utc_offset_h: number;
}

export interface NoaaStation {
  GHCN_ID: string;
  NAME: string;
  STATE?: string;
  LATITUDE?: number;
  LONGITUDE?: number;
  dist_miles: number;
  elev_delta_ft?: number;
  elevation_ft?: number;
  recommendation_status?: "green" | "yellow" | "red";
  is_preferred?: boolean;
}

export interface AshraStation {
  wmo: string;
  station: string;
  dist_miles: number;
  elev_ft?: number;
  lat?: number;
  lon?: number;
}

export interface StationsResult {
  noaa: NoaaStation[];
  recommended_station_id: string | null;
  recommendation_message: string;
  ashrae: AshraStation[];
  noaa_error?: string | null;
}

export interface DesignConditions {
  [key: string]: unknown;
}

export interface ProcessResult {
  result_token: string;
  filter_used: string;
  n_rows: number;
  meta: {
    station_name: string;
    station_id: string;
    pressure_psi: number;
    distance_miles: number;
    delta_time: number;
    timezone: string;
    elevation_delta_ft: number;
    site_ele_m: number;
    site_ele_ft: number;
  };
  design_conditions: DesignConditions;
  psychro_qa: {
    status: "pass" | "warn";
    metrics: Record<string, number>;
    messages: string[];
  };
  processing_qa?: {
    status: "pass" | "warn";
    metrics: {
      rows_original: number;
      rows_resample: number;
      rows_replacement: number;
      rows_interpolated: number;
      rows_winterization: number;
      filled_TMP_F: number;
      filled_DEW_F: number;
      remaining_nan: number;
      avg_missing_pct: number;
      window_10y: string;
      window_15y: string;
    };
    messages: string[];
  };
  winterization?: {
    no_freeze_start: string | null;
    no_freeze_end: string | null;
  };
}

export interface FilterScore {
  name: string;
  label: string;
  rows: number;
  coverage_pct: number;
  recommended: boolean;
  error?: string;
}

export interface OmStat {
  "%": number;
  DB_F?: number; DB_C?: number;
  WB_F?: number; WB_C?: number;
  MCWB_F?: number; MCWB_C?: number;
  MCDB_F?: number; MCDB_C?: number;
}

export interface OmResult {
  stats: OmStat[];
  yearly: Record<string, unknown>[];
  winterization: {
    no_freeze_start: string | null;
    no_freeze_end: string | null;
  };
  om_token?: string;
}

// ── API calls ────────────────────────────────────────────────────

export const geocode = (q: string) =>
  http.get<{ results: { display_name: string; lat: number; lon: number }[] }>("/geocode", { params: { q } }).then((r) => r.data);

export const confirmSite = (lat: number, lon: number, units = "F", acf = 1.0) =>
  http.post<SiteInfo>("/site/confirm", { lat, lon, units, acf }).then((r) => r.data);

export const getStations = (lat: number, lon: number, elevation_m = 0) =>
  http.get<StationsResult>("/stations", { params: { lat, lon, elevation_m } }).then((r) => r.data);

export const checkAvailability = (station_id: string, year_start = 2000, year_end = 2025) =>
  http
    .get<{ station_id: string; available_years: number[] }>("/availability", {
      params: { station_id, year_start, year_end },
    })
    .then((r) => r.data);

export const getBulkAvailability = (station_ids: string[], year_start = 2015, year_end = new Date().getFullYear() - 1) =>
  http
    .get<{ availability: Record<string, number[]> }>("/bulk-availability", {
      params: { station_ids: station_ids.join(","), year_start, year_end },
    })
    .then((r) => r.data.availability);

export const processData = (
  token: string,
  params: {
    station_id: string;
    years: number[];
    units: string;
    lat: number;
    lon: number;
    elevation_m: number;
    filter_type?: string;
    exclude_quality_codes?: string[];
    clip_lower_f?: number;
    clip_upper_f?: number | null;
    clip_lower_dew_f?: number;
    clip_upper_dew_f?: number | null;
  }
) =>
  http
    .post<ProcessResult>("/process", params, { params: { token } })
    .then((r) => r.data);

export const getOpenMeteo = (lat: number, lon: number, year_start = 2015, year_end = 2024, units = "F") =>
  http
    .get("/openmeteo", { params: { lat, lon, year_start, year_end, units } })
    .then((r) => r.data);

export const scoreFilters = (token: string, excludeQualityCodes: string[] = ["2", "3"]) => {
  const params = new URLSearchParams({ token });
  excludeQualityCodes.forEach((c) => params.append("exclude_quality_codes", c));
  return http.post<{
    filters: FilterScore[];
    recommended: string;
    total_rows: number;
    clean_qa: Record<string, unknown>;
  }>(`/score-filters?${params}`).then((r) => r.data);
};

export const getPsychroChart = (token: string, units = "F") =>
  http.get<{ image_b64: string; format: string }>("/chart/psychrometric", { params: { token, units } }).then((r) => r.data);

export const getScatterData = (token: string, units = "F") =>
  http.get<{ points: { x: number; y: number }[]; units: string }>("/chart/scatter-data", { params: { token, units } }).then((r) => r.data);

export const getDensityData = (token: string, units = "F", bins = 60) =>
  http.get<{ cells: { x: number; y: number; v: number }[]; x_width: number; y_height: number; max_v: number; units: string }>(
    "/chart/density-data", { params: { token, units, bins } }
  ).then((r) => r.data);

export const getHeatmapData = (token: string, units = "F") =>
  http.get<{ cells: { month: string; year: number; value: number }[]; units: string }>("/chart/heatmap-data", { params: { token, units } }).then((r) => r.data);

export type MonthlyPoint = { month: string; tdb_mean: number; twb_mean: number; tdb_p10: number; tdb_p90: number; twb_p10: number; twb_p90: number };
export const getMonthlyData = (token: string, units = "F") =>
  http.get<{ months: MonthlyPoint[]; units: string }>("/chart/monthly-data", { params: { token, units } }).then((r) => r.data);

export const getFreezingData = (token: string) =>
  http.get<{ bars: { week: number; hours: number }[]; threshold_f: number }>("/chart/freezing-data", { params: { token } }).then((r) => r.data);

export const downloadCsv = (token: string, stationId: string) => {
  const url = `${BASE}/download-csv?token=${encodeURIComponent(token)}`;
  const a = document.createElement("a");
  a.href = url;
  a.download = `${stationId}_merged.csv`;
  a.click();
};

export const downloadResults = (token: string, stationId: string) => {
  const url = `${BASE}/download-results?token=${encodeURIComponent(token)}`;
  const a = document.createElement("a");
  a.href = url;
  a.download = `${stationId}_results.csv`;
  a.click();
};

export interface AshraConditionLevels {
  tdb: number | null; mcwb: number | null; twb: number | null; mcdb: number | null;
}
export interface AshraConditionResult {
  wmo: string;
  station?: string;
  ashrae_version?: string;
  pressure_psia?: number | null;
  levels?: { "0.4": AshraConditionLevels; "1": AshraConditionLevels; "2": AshraConditionLevels };
  error?: string;
}

export const getAshraConditions = (wmos: string[], edition = "2025", si_ip = "IP") =>
  http.post<{ results: AshraConditionResult[] }>("/ashrae/conditions", { wmos, edition, si_ip }).then((r) => r.data);

// ── SSE fetch stream ─────────────────────────────────────────────

export interface FetchProgress {
  event: "start" | "progress" | "done";
  i?: number;
  total?: number;
  year?: number;
  status?: string;
  rows?: number;
  pct?: number;
  token?: string;
  years_loaded?: number[];
}

export function streamFetch(
  station_id: string,
  years: number[],
  units: string,
  onProgress: (p: FetchProgress) => void
): Promise<string> {
  return new Promise((resolve, reject) => {
    fetch(`${BASE}/fetch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ station_id, years, units }),
    })
      .then((res) => {
        if (!res.ok || !res.body) return reject(new Error(`HTTP ${res.status}`));
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        const pump = (): Promise<void> =>
          reader.read().then(({ done, value }) => {
            if (done) return;
            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split("\n\n");
            buffer = parts.pop() ?? "";

            for (const chunk of parts) {
              const eventLine = chunk.match(/^event: (.+)$/m)?.[1];
              const dataLine = chunk.match(/^data: (.+)$/m)?.[1];
              if (!eventLine || !dataLine) continue;
              try {
                const parsed = JSON.parse(dataLine) as FetchProgress;
                parsed.event = eventLine as FetchProgress["event"];
                onProgress(parsed);
                if (eventLine === "done" && parsed.token) resolve(parsed.token);
              } catch {
                // ignore parse errors
              }
            }
            return pump();
          });

        pump().catch(reject);
      })
      .catch(reject);
  });
}
