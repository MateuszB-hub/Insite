import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  fetchMe,
  login as apiLogin,
  logout as apiLogout,
  register as apiRegister,
  type AuthUser,
} from '../lib/api'

interface AuthState {
  user: AuthUser | null
  /** True until the initial session check finishes. Guards must wait on this. */
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (p: { email: string; password: string; fullName?: string; acceptTerms: boolean; inviteCode?: string }) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  // Session lives in an httpOnly cookie, so the only way to know who we are
  // is to ask the server.
  useEffect(() => {
    let cancelled = false
    fetchMe()
      .then((u) => !cancelled && setUser(u))
      .catch(() => !cancelled && setUser(null))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    setUser(await apiLogin(email, password))
  }, [])

  const register = useCallback(
    async (p: { email: string; password: string; fullName?: string; acceptTerms: boolean; inviteCode?: string }) => {
      setUser(await apiRegister(p))
    },
    [],
  )

  const logout = useCallback(async () => {
    await apiLogout()
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
