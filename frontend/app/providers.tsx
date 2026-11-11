"use client";

import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api/client";
import { ToastProvider } from "@/components/ui/Toast";
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
      defaultOptions: {
        queries: {
          staleTime: 30_000,
          // a refusal (401, 403, 404, 422) will not change by asking again; only server and network trouble is retried once
          retry: (count, error) => count < 1 && !(error instanceof ApiError && error.status < 500),
          refetchOnWindowFocus: false,
        },
      },
    });
    return c;
  });
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>
        <ToastProvider>{children}</ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
