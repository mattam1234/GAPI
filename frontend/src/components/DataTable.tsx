import { useState } from 'react'
import {
  type ColumnDef, flexRender, getCoreRowModel,
  getSortedRowModel, type SortingState, useReactTable,
} from '@tanstack/react-table'
import { EmptyState, Skeleton } from './Card'

interface Props<T> {
  columns: ColumnDef<T, any>[]
  data: T[]
  loading?: boolean
  empty?: string
}

export function DataTable<T>({ columns, data, loading, empty = 'No data yet' }: Props<T>) {
  const [sorting, setSorting] = useState<SortingState>([])
  const table = useReactTable({
    data, columns, state: { sorting }, onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(),
  })

  if (loading) {
    return (
      <div style={{ display: 'grid', gap: 10 }}>
        {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} height={20} />)}
      </div>
    )
  }
  if (!data.length) return <EmptyState label={empty} />

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="tbl">
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => {
                const sorted = h.column.getIsSorted()
                return (
                  <th key={h.id} onClick={h.column.getToggleSortingHandler()}>
                    {flexRender(h.column.columnDef.header, h.getContext())}
                    <span className="sort">{sorted === 'asc' ? '▲' : sorted === 'desc' ? '▼' : '↕'}</span>
                  </th>
                )
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
