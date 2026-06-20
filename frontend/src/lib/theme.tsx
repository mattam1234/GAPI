// Theme provider + hook. Sets [data-theme] on <html>, persists choice, and exposes
// readTokens() so the Recharts components can read the live CSS-variable palette.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

type Mode = 'dark' | 'light'

interface ThemeCtx {
  mode: Mode
  toggle: () => void
  setMode: (m: Mode) => void
}

const STORAGE_KEY = 'gapi-theme'
const Ctx = createContext<ThemeCtx | null>(null)

function initialMode(): Mode {
  if (typeof window === 'undefined') return 'dark'
  const saved = window.localStorage.getItem(STORAGE_KEY)
  if (saved === 'dark' || saved === 'light') return saved
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>(initialMode)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', mode)
    try { window.localStorage.setItem(STORAGE_KEY, mode) } catch { /* ignore */ }
  }, [mode])

  const toggle = useCallback(() => setMode((m) => (m === 'dark' ? 'light' : 'dark')), [])
  const value = useMemo<ThemeCtx>(() => ({ mode, toggle, setMode }), [mode, toggle])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}

export interface Tokens {
  surface: string
  border: string
  text: string
  muted: string
  grid: string
  series: string[]
}

/** Read the live design-token palette off :root so charts re-theme instantly. */
export function readTokens(): Tokens {
  const cs = typeof window !== 'undefined' ? getComputedStyle(document.documentElement) : null
  const v = (name: string, fallback: string) => (cs?.getPropertyValue(name).trim() || fallback)
  return {
    surface: v('--surface', '#181b26'),
    border: v('--border', '#2a2f3e'),
    text: v('--text', '#e8eaf2'),
    muted: v('--text-muted', '#9aa1b4'),
    grid: v('--grid', 'rgba(255,255,255,.06)'),
    series: [
      v('--c1', '#6d5efc'), v('--c2', '#2dd4bf'), v('--c3', '#f59e0b'),
      v('--c4', '#fb7185'), v('--c5', '#38bdf8'), v('--c6', '#a78bfa'),
    ],
  }
}
