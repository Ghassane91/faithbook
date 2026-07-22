import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api, setUnauthorizedHandler } from './api'
import type { User } from './types'

interface AuthState {
  user: User | null
  pret: boolean // premier /me terminé (évite un flash de l'écran de connexion)
  connexion: (email: string, password: string) => Promise<void>
  deconnexion: () => Promise<void>
  rafraichir: () => Promise<void>
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [pret, setPret] = useState(false)

  const rafraichir = useCallback(async () => {
    try {
      setUser(await api.me())
    } catch {
      setUser(null)
    }
  }, [])

  useEffect(() => {
    // Une session expirée en cours d'usage ramène proprement à la connexion.
    setUnauthorizedHandler(() => setUser(null))
    rafraichir().finally(() => setPret(true))
  }, [rafraichir])

  const connexion = useCallback(async (email: string, password: string) => {
    setUser(await api.login(email, password))
  }, [])

  const deconnexion = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setUser(null)
    }
  }, [])

  return (
    <Ctx.Provider value={{ user, pret, connexion, deconnexion, rafraichir }}>
      {children}
    </Ctx.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAuth hors AuthProvider')
  return ctx
}
