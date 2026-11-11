"use client";

import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api/client";
import { AuthProvider } from "@/lib/auth";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => {
    const c: QueryClient = new QueryClient({
      queryCache: new QueryCache({
        onError: (error, query) => {
          // a session that ended while the page was open: ask who we are again, which sends the user to sign in
          if (error instanceof ApiError && error.status === 401 && query.queryKey[0] !== "me") void c.invalidateQueries({ queryKey: ["me"] });
        },
      }),
      defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false } },
    });
    return c;
  });
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}
