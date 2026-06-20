// Thin typed fetch wrapper. Same-origin in production (served under /app), proxied
// in dev (see vite.config.ts). `credentials: 'include'` carries the Flask session
// cookie that backend/dependencies.py decodes, so auth is shared with the app.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  const ct = res.headers.get('content-type') ?? ''
  const body = ct.includes('application/json') ? await res.json().catch(() => null) : await res.text()
  if (!res.ok) {
    const msg = (body && typeof body === 'object' && 'error' in body) ? String(body.error) : `Request failed (${res.status})`
    throw new ApiError(res.status, msg)
  }
  return body as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: 'POST', body: data == null ? undefined : JSON.stringify(data) }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
