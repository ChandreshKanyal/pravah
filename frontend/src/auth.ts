// Sign-in (policy review): Firebase Authentication with Google accounts, loaded only when the Firebase web config is set
// (VITE_FIREBASE_API_KEY, VITE_FIREBASE_AUTH_DOMAIN). Without it the prototype runs open and approvals ask for a typed name.
import { useEffect, useState } from "react";

const cfg = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY as string | undefined,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined,
  projectId: (import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined) ?? "project-0fd9c4ae-bf90-452f-a80",
};
export const authConfigured = !!(cfg.apiKey && cfg.authDomain);

export type User = { name: string; email: string; photo: string | null };
type Fb = { auth: any; mod: typeof import("firebase/auth") };
let fb: Promise<Fb> | null = null;
let current: User | null = null;
const listeners = new Set<(u: User | null) => void>();

function load(): Promise<Fb> {
  if (!fb) fb = (async () => {
    const [{ initializeApp }, mod] = await Promise.all([import("firebase/app"), import("firebase/auth")]);
    const auth = mod.getAuth(initializeApp(cfg));
    mod.onAuthStateChanged(auth, (u: any) => {
      current = u ? { name: u.displayName ?? u.email ?? "", email: u.email ?? "", photo: u.photoURL } : null;
      listeners.forEach((f) => f(current));
    });
    return { auth, mod };
  })();
  return fb;
}

export async function idToken(): Promise<string | null> {
  if (!authConfigured) return null;
  const { auth } = await load();
  return auth.currentUser ? auth.currentUser.getIdToken() : null;
}

export async function signIn() {
  const { auth, mod } = await load();
  await mod.signInWithPopup(auth, new mod.GoogleAuthProvider());
}

export async function signOut() {
  const { auth, mod } = await load();
  await mod.signOut(auth);
}

export function useUser(): User | null {
  const [u, setU] = useState<User | null>(current);
  useEffect(() => {
    if (!authConfigured) return;
    listeners.add(setU);
    load().catch(() => undefined);
    return () => { listeners.delete(setU); };
  }, []);
  return u;
}
