const BASE = import.meta.env.VITE_API_BASE ?? "/api";

export type Health = { ok: boolean; ee: boolean; vertex: boolean; firestore: boolean };

export async function getHealth(): Promise<Health> {
  const r = await fetch(`${BASE}/health`);
  if (!r.ok) throw new Error(`health ${r.status}`);
  return r.json();
}
