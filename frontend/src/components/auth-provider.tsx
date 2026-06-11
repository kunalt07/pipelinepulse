"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { api, UnauthorizedError, type CurrentUser } from "@/lib/api";

type AuthState =
  | { status: "loading" }
  | { status: "authenticated"; user: CurrentUser }
  | { status: "unauthenticated" };

type Ctx = {
  state: AuthState;
  user: CurrentUser | null;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<Ctx | null>(null);

const PUBLIC_PATHS = new Set(["/login", "/signup"]);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname() ?? "/";
  const [state, setState] = useState<AuthState>({ status: "loading" });

  const refresh = useCallback(async () => {
    try {
      const user = await api.authMe();
      setState({ status: "authenticated", user });
    } catch (e) {
      if (e instanceof UnauthorizedError) {
        setState({ status: "unauthenticated" });
      } else {
        // Other errors (network, 5xx): treat as unauthenticated so user can retry.
        setState({ status: "unauthenticated" });
      }
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.authLogout();
    } catch {
      // ignore — proceed with client-side logout regardless
    }
    setState({ status: "unauthenticated" });
    router.push("/login");
  }, [router]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Redirect logic: authed users away from /login & /signup; unauthed users to /login.
  useEffect(() => {
    if (state.status === "loading") return;
    const isPublic = PUBLIC_PATHS.has(pathname);
    if (state.status === "unauthenticated" && !isPublic) {
      router.replace("/login");
    } else if (state.status === "authenticated" && isPublic) {
      router.replace("/");
    }
  }, [state.status, pathname, router]);

  // While loading, render a minimal placeholder so the dashboard doesn't flash unauthed data.
  if (state.status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Unauthenticated + on a private route — let the redirect effect navigate;
  // render nothing to avoid flashing.
  if (state.status === "unauthenticated" && !PUBLIC_PATHS.has(pathname)) {
    return null;
  }

  // Authenticated + on a public route — same: redirect effect handles it.
  if (state.status === "authenticated" && PUBLIC_PATHS.has(pathname)) {
    return null;
  }

  return (
    <AuthContext.Provider
      value={{
        state,
        user: state.status === "authenticated" ? state.user : null,
        refresh,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): Ctx {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    // Outside the provider — happens on /login & /signup. Return a stub that the
    // login/signup pages don't actually use.
    return {
      state: { status: "unauthenticated" },
      user: null,
      refresh: async () => {},
      logout: async () => {},
    };
  }
  return ctx;
}

export function useCurrentUser(): CurrentUser | null {
  return useAuth().user;
}
