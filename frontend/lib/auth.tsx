"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { ApiError, api } from "@/lib/api/client";
import type { User } from "@/lib/schemas";

export type Auth = {
  user: User | null;
  loading: boolean;
  /** Whether the signed-in user's role holds a permission. The server enforces it; this only hides what would be refused. */
  can: (permission: string) => boolean;
  /** Call after a successful sign-in (the answer already carries the user). */
  signedIn: (user: User) => void;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return (await api.me()).user;
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null; // not signed in is an answer, not a failure
        throw e;
      }
    },
    retry: false,
    staleTime: 60_000,
  });
  const user = me.data ?? null;
  const signedIn = useCallback((u: User) => qc.setQueryData(["me"], u), [qc]);
  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" }); // nothing from the previous user stays in memory
      qc.setQueryData(["me"], null);
    }
  }, [qc]);
  const value = useMemo<Auth>(
    () => ({ user, loading: me.isLoading, can: (p) => user?.permissions.includes(p) ?? false, signedIn, signOut }),
    [user, me.isLoading, signedIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const v = useContext(AuthContext);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

/** Only same-site paths are followed after sign-in; anything else (an absolute or protocol-relative URL) is ignored. */
export function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/login") ? next : "/overview";
}

