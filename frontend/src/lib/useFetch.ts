// Tiny data-fetching hook: runs an async loader, tracks loading/error, and exposes
// reload(). Guards against setting state after unmount / out-of-order responses.
import { useCallback, useEffect, useRef, useState, type DependencyList } from 'react'

interface State<T> {
  data: T | null
  loading: boolean
  error: string | null
}

export function useFetch<T>(loader: () => Promise<T>, deps: DependencyList = []) {
  const [state, setState] = useState<State<T>>({ data: null, loading: true, error: null })
  const reqId = useRef(0)

  const run = useCallback(() => {
    const id = ++reqId.current
    setState((s) => ({ ...s, loading: true, error: null }))
    loader()
      .then((data) => {
        if (id === reqId.current) setState({ data, loading: false, error: null })
      })
      .catch((e: unknown) => {
        if (id === reqId.current) {
          setState({ data: null, loading: false, error: e instanceof Error ? e.message : String(e) })
        }
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    run()
    return () => { reqId.current++ } // invalidate in-flight on unmount/dep-change
  }, [run])

  return { ...state, reload: run }
}
