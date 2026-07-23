import type {
  Account,
  Health,
  Job,
  LoginStatus,
  MetricsSeries,
  Run,
  RunSummary,
  SessionStatus,
  SessionTest,
  Target,
  TargetInput,
  User,
} from './types'

// Meme origine : nginx relaie /api vers le backend. Aucune URL a configurer.
const BASE = '/api'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

// Rappel invoque a chaque 401 : permet au contexte d'auth de basculer sur
// l'ecran de connexion, meme si la session expire au milieu d'une navigation.
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    let detail = `Erreur ${res.status}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: any) => d.msg).join(' · ')
    } catch {
      /* reponse sans corps JSON */
    }
    // La connexion et /me gerent leur propre 401 : ne pas declencher la
    // redirection globale pour eux, sinon on masque le message d'erreur.
    if (res.status === 401 && onUnauthorized && !path.startsWith('/auth/')) onUnauthorized()
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const api = {
  login: (email: string, password: string) =>
    request<User>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),
  me: () => request<User>('/auth/me'),
  changePassword: (current_password: string, new_password: string) =>
    request<User>('/auth/password', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password }),
    }),
  forgotPassword: (email: string) =>
    request<{ detail: string }>('/auth/forgot', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),
  resetPassword: (token: string, new_password: string) =>
    request<{ detail: string }>('/auth/reset', {
      method: 'POST',
      body: JSON.stringify({ token, new_password }),
    }),

  health: () => request<Health>('/health'),
  jobs: () => request<Job[]>('/scheduler/jobs'),

  targets: () => request<Target[]>('/targets'),
  target: (id: number) => request<Target>(`/targets/${id}`),
  createTarget: (data: TargetInput) =>
    request<Target>('/targets', { method: 'POST', body: JSON.stringify(data) }),
  updateTarget: (id: number, data: TargetInput) =>
    request<Target>(`/targets/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteTarget: (id: number) => request<void>(`/targets/${id}`, { method: 'DELETE' }),
  runNow: (id: number, force = false) =>
    request<{ run_id: number; status: string; detail: string }>(
      `/targets/${id}/run${force ? '?force=true' : ''}`,
      { method: 'POST' },
    ),
  sessionStatus: (id: number) => request<SessionStatus>(`/targets/${id}/session`),
  targetMetrics: (id: number) => request<MetricsSeries>(`/targets/${id}/metrics`),

  accounts: () => request<Account[]>('/accounts'),
  createAccount: (name: string, platform = 'facebook') =>
    request<Account>('/accounts', { method: 'POST', body: JSON.stringify({ name, platform }) }),
  deleteAccount: (id: number) => request<void>(`/accounts/${id}`, { method: 'DELETE' }),
  loginStart: (id: number) =>
    request<LoginStatus>(`/accounts/${id}/login/start`, { method: 'POST' }),
  loginStatus: (id: number) => request<LoginStatus>(`/accounts/${id}/login/status`),
  loginFinish: (id: number) =>
    request<SessionTest>(`/accounts/${id}/login/finish`, { method: 'POST' }),
  loginCancel: (id: number) =>
    request<void>(`/accounts/${id}/login/cancel`, { method: 'POST' }),
  testAccount: (id: number) => request<SessionTest>(`/accounts/${id}/test`, { method: 'POST' }),

  runs: (params: Record<string, string | number | undefined> = {}) => {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') q.set(k, String(v))
    return request<{ total: number; items: RunSummary[] }>(`/runs?${q}`)
  },
  run: (id: number) => request<Run>(`/runs/${id}`),
  screenshotUrl: (id: number) => `${BASE}/runs/${id}/screenshot`,
  thumbnailUrl: (id: number) => `${BASE}/runs/${id}/thumbnail`,
}
