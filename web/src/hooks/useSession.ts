import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage, setUnauthorizedHandler, type User } from '../api/client'

export type SessionStatus = 'booting' | 'anon' | 'authed'

export interface Session {
  status: SessionStatus
  user: User | null
  error: string | null
  login: (account: string, password: string) => Promise<void>
  register: (account: string, password: string, name: string) => Promise<void>
  logout: () => Promise<void>
  dismissError: () => void
}

export function useSession(): Session {
  const [status, setStatus] = useState<SessionStatus>('booting')
  const [user, setUser] = useState<User | null>(null)
  const [error, setError] = useState<string | null>(null)

  // 任何接口返回 401，都回落到未登录态，而不是让页面停在半死状态
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setStatus('anon')
      setUser(null)
    })
    return () => setUnauthorizedHandler(null)
  }, [])

  useEffect(() => {
    void (async () => {
      try {
        const body = await api.auth.me()
        setUser(body.user)
        setStatus('authed')
      } catch {
        setStatus('anon')
      }
    })()
  }, [])

  const login = useCallback(async (account: string, password: string) => {
    setError(null)
    try {
      const body = await api.auth.login(account.trim(), password)
      setUser(body.user)
      setStatus('authed')
    } catch (cause) {
      setError(errorMessage(cause))
      throw cause
    }
  }, [])

  const register = useCallback(async (account: string, password: string, name: string) => {
    setError(null)
    try {
      const body = await api.auth.register(account.trim(), password, name.trim())
      setUser(body.user)
      setStatus('authed')
    } catch (cause) {
      setError(errorMessage(cause))
      throw cause
    }
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.auth.logout()
    } finally {
      setUser(null)
      setStatus('anon')
    }
  }, [])

  return {
    status,
    user,
    error,
    login,
    register,
    logout,
    dismissError: () => setError(null),
  }
}
