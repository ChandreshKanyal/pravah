import { useEffect, useState } from "react";
import { getHealth, Health } from "./api/client";

const mark = (v: boolean) => (v ? "✓" : "✗");

export default function App() {
  const [h, setH] = useState<Health | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getHealth().then(setH).catch((e) => setErr(String(e)));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 640, margin: "4rem auto", padding: "0 1rem" }}>
      <h1>Hello Pravah</h1>
      {err && <p>Health check failed: {err}</p>}
      {!h && !err && <p>Checking…</p>}
      {h && (
        <p style={{ fontSize: "1.25rem" }}>
          ee {mark(h.ee)} vertex {mark(h.vertex)} firestore {mark(h.firestore)}
        </p>
      )}
      <p style={{ fontSize: "0.85rem", color: "#555" }}>
        <strong>Decision-support draft, not a prediction or an order.</strong> Pravah uses simplified, uncalibrated
        planning models (HAND flood mapping, rational-method runoff, susceptibility indices). Results are estimates
        for planning and must be reviewed by qualified officials before any action.
      </p>
    </main>
  );
}
