import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

// Auth is gated on the server secret; keyless dev = pass-through middleware.
const enabled = !!process.env.CLERK_SECRET_KEY;
// "/" is the public marketing landing; everything else (e.g. /app) stays gated.
const isPublic = createRouteMatcher(["/", "/sign-in(.*)", "/sign-up(.*)"]);

export default enabled
  ? clerkMiddleware(async (auth, req) => {
      if (!isPublic(req)) await auth.protect();
    })
  : function middleware() {
      return NextResponse.next();
    };

export const config = {
  // Run on app routes (skip Next internals and static files).
  matcher: ["/((?!_next|.*\\..*).*)"],
};
