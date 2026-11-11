/** Pages a visitor can open without being signed in. The server and the page gate both use this one list. */
export const PUBLIC_PATHS = ["/login", "/forgot-password", "/accept-invite", "/reset-password"] as const;
export const isPublicPath = (path: string): boolean => PUBLIC_PATHS.some((p) => path === p);
