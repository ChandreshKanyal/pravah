// Field photos taken without signal are kept on the device (IndexedDB) and uploaded when the connection returns.
// Nothing leaves the device until the upload succeeds; the queue is per browser.
export type Queued = { id: string; aoiId: string; kind: "building" | "drain"; blob: Blob; name: string; pin: { lat: number; lng: number } | null; at: string };

const DB = "pravah-field", STORE = "queue";

function db(): Promise<IDBDatabase> {
  return new Promise((res, rej) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: "id" });
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}

async function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const d = await db();
  return new Promise((res, rej) => {
    const r = fn(d.transaction(STORE, mode).objectStore(STORE));
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}

export const enqueue = (q: Queued) => tx("readwrite", (s) => s.put(q));
export const remove = (id: string) => tx("readwrite", (s) => s.delete(id));
export async function list(aoiId: string): Promise<Queued[]> {
  try { return ((await tx("readonly", (s) => s.getAll())) as Queued[]).filter((q) => q.aoiId === aoiId); } catch { return []; }
}

/** Downscale a photo to save mobile data (only when a pin is known: canvas drops EXIF GPS). */
export async function shrink(f: File, max = 1600): Promise<Blob> {
  if (f.size < 1_500_000) return f;
  const bmp = await createImageBitmap(f);
  const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
  c.getContext("2d")!.drawImage(bmp, 0, 0, c.width, c.height);
  return new Promise((res) => c.toBlob((b) => res(b ?? f), "image/jpeg", 0.82));
}
