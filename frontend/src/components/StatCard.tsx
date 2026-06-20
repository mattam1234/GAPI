import { Skeleton } from './Card'

interface Props {
  label: string
  value: string
  delta?: { dir: 'up' | 'down' | 'flat'; text: string }
  loading?: boolean
}

const arrow = { up: '▲', down: '▼', flat: '◆' }

export function StatCard({ label, value, delta, loading }: Props) {
  return (
    <article className="card card-pad stat">
      <span className="label">{label}</span>
      {loading ? (
        <Skeleton height={30} width={90} />
      ) : (
        <span className="value">{value}</span>
      )}
      {delta && !loading && (
        <span className={`delta ${delta.dir}`}>
          {arrow[delta.dir]} {delta.text}
        </span>
      )}
    </article>
  )
}
