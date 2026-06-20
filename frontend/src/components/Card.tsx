import type { ReactNode } from 'react'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`card card-pad ${className}`}>{children}</section>
}

export function CardHead({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <header className="card-head">
      <h3>{title}</h3>
      {action}
    </header>
  )
}

export function Skeleton({ height = 16, width = '100%' }: { height?: number; width?: number | string }) {
  return <div className="skeleton" style={{ height, width }} aria-hidden />
}

export function EmptyState({ icon = '∅', label }: { icon?: string; label: string }) {
  return (
    <div className="empty">
      <div style={{ fontSize: 28, opacity: 0.5 }}>{icon}</div>
      <p>{label}</p>
    </div>
  )
}
