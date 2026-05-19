# new_weather_app

React + FastAPI rewrite of the weather analysis tool.

## Dev

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev        # http://localhost:5173
```

## Stack
- **Backend**: FastAPI + existing pipeline modules (psychrometrics, NOAA download, ASHRAE)
- **Frontend**: React 19 + TypeScript + Vite + Tailwind CSS + Zustand

## Endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/site/confirm` | Elevation, pressure, timezone |
| GET  | `/api/stations` | Ranked NOAA + ASHRAE stations |
| GET  | `/api/availability` | Available NOAA years |
| POST | `/api/fetch` | SSE stream: download years |
| POST | `/api/process` | Merge → filter → psychrometrics |
| GET  | `/api/results/{token}` | Stored process result |
| GET  | `/api/chart/psychrometric` | Psychrometric chart PNG |
| GET  | `/api/openmeteo` | Open-Meteo quick estimate |
