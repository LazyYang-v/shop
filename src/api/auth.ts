export type User = {
  id: string
  email: string
  role: 'buyer' | 'admin'
}

type CsrfResponse = { csrf_token: string }
type AuthResponse = { user: User }

export let csrfToken: string | null = null

export async function refreshCsrfToken(): Promise<string> {
  const response = await fetch('/api/auth/csrf', { credentials: 'same-origin', cache: 'no-store' })
  if (!response.ok) throw new Error('无法获取安全令牌，请刷新页面后重试。')
  const body = (await response.json()) as CsrfResponse
  csrfToken = body.csrf_token
  return csrfToken
}

export async function getCsrfToken(): Promise<string> {
  return csrfToken ?? refreshCsrfToken()
}

export function notifySessionExpired() {
  csrfToken = null
  window.dispatchEvent(new CustomEvent('auth:expired'))
}

async function request<T>(path: string, init?: RequestInit, notifyAuthExpired = true): Promise<T> {
  const response = await fetch(path, { credentials: 'same-origin', ...init })
  if (response.status === 401 && notifyAuthExpired) {
    notifySessionExpired()
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string }
    throw new Error(body.detail ?? `请求失败 (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

async function mutate<T>(path: string, body?: unknown): Promise<T> {
  const token = await getCsrfToken()
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export const authApi = {
  register: (email: string, password: string) =>
    mutate<{ message: string }>('/api/auth/register', { email, password }),
  login: async (email: string, password: string) => {
    const user = await mutate<AuthResponse>('/api/auth/login', { email, password })
    csrfToken = null
    await refreshCsrfToken()
    return user.user
  },
  logout: async () => {
    await mutate<void>('/api/auth/logout')
    csrfToken = null
  },
  me: () => request<User>('/api/auth/me', undefined, false),
  adminAccess: () => request<User>('/api/admin/access'),
}
