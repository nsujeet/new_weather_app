import { useRef, useState } from "react";
import { useStore } from "../store";
import type { AppState } from "../store";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api";

interface Msg { role: "user" | "assistant"; content: string; }

function buildContext(store: AppState) {
  const { stage, units, lat, lon, siteInfo, selectedStation, selectedYears,
    ashraConditions, processResult } = store;
  return {
    stage, units, lat, lon,
    elevation_ft: siteInfo?.elevation_ft,
    pressure_psi: siteInfo?.pressure_psi,
    timezone: siteInfo?.timezone,
    selectedStation,
    selectedYears,
    ashrae_stations: ashraConditions.slice(0, 3).map((a) => ({
      wmo: a.wmo, station: a.station, pressure_psia: a.pressure_psia,
      levels_1pct: a.levels?.["1"],
    })),
    design_conditions: processResult ? {
      filter: processResult.filter_used,
      n_rows: processResult.n_rows,
      distance_miles: processResult.meta.distance_miles,
      pressure_psi: processResult.meta.pressure_psi,
      station: processResult.meta.station_name,
    } : null,
  };
}

export default function ChatPanel({ suggestions }: { suggestions: string[] }) {
  const store = useStore();
  const [msgs, setMsgs]     = useState<Msg[]>([]);
  const [input, setInput]   = useState("");
  const [busy, setBusy]     = useState(false);
  const bottomRef           = useRef<HTMLDivElement>(null);

  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    const userMsg: Msg = { role: "user", content: text.trim() };
    const newMsgs = [...msgs, userMsg];
    setMsgs(newMsgs);
    setInput("");
    setBusy(true);

    const assistantMsg: Msg = { role: "assistant", content: "" };
    setMsgs([...newMsgs, assistantMsg]);

    try {
      const resp = await fetch(`${BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text.trim(),
          history: newMsgs.slice(-8).map((m) => ({ role: m.role, content: m.content })),
          context: buildContext(store),
        }),
      });
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = "";

      const pump = async (): Promise<void> => {
        const { done, value } = await reader.read();
        if (done) return;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() ?? "";
        for (const chunk of parts) {
          const line = chunk.match(/^data: (.+)$/m)?.[1];
          if (!line) continue;
          try {
            const parsed = JSON.parse(line);
            if (parsed.text) {
              setMsgs((prev) => {
                const copy = [...prev];
                copy[copy.length - 1] = {
                  ...copy[copy.length - 1],
                  content: copy[copy.length - 1].content + parsed.text,
                };
                return copy;
              });
              bottomRef.current?.scrollIntoView({ behavior: "smooth" });
            }
          } catch { /* ignore */ }
        }
        return pump();
      };
      await pump();
    } catch (e: unknown) {
      setMsgs((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = { role: "assistant", content: "Error: " + (e instanceof Error ? e.message : String(e)) };
        return copy;
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="wa-chat-header">Ask a question</div>

      <div className="wa-messages">
        {msgs.length === 0 && (
          <div className="wa-empty-chat">
            Ask about design conditions,<br />psychrometrics, or data quality.
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`wa-bubble wa-bubble-${m.role}`}>
            <div className="wa-bubble-label">{m.role === "user" ? "You" : "Assistant"}</div>
            {m.content || (busy && i === msgs.length - 1 ? "…" : "")}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions */}
      {msgs.length === 0 && suggestions.length > 0 && (
        <div className="wa-suggestions">
          {suggestions.map((s) => (
            <button key={s} className="wa-suggestion-chip" onClick={() => send(s)}>
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="wa-chat-input-row">
        <textarea
          className="wa-chat-input"
          rows={1}
          placeholder="Ask anything…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
        />
        <button className="wa-send-btn" onClick={() => send(input)} disabled={busy || !input.trim()}>
          Send
        </button>
      </div>
    </>
  );
}
