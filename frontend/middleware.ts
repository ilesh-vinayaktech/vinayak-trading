import { NextResponse, type NextRequest } from "next/server";
import { isPublicPath } from "@/lib/publicPaths";

/** Pages are only handed to a browser that holds a session cookie; everyone else is sent to the sign-in page before any
 * app code is served. This checks presence only: the API validates the session on every data request. */
export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  if (isPublicPath(pathname) || req.cookies.has("session") || req.cookies.has("__Host-session")) return NextResponse.next();
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = `?next=${encodeURIComponent(pathname + search)}`;
  return NextResponse.redirect(url);
}

// not for the API (it answers 401 itself), framework files or the icon
export const config = { matcher: ["/((?!api/|_next/|icon.svg).*)"] };
