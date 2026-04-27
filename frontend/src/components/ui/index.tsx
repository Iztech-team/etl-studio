import { useEffect, useRef, useState } from 'react'
import { Loader2, Database, Upload, Pencil, Settings2, Wand2, Download, BarChart3, GitBranch } from 'lucide-react'
import { PHASES, type Phase } from '../../store/pipeline'
import { Progress } from '@/components/ui/progress'

const PHASE_ICONS: Record<Phase, typeof Upload> = {
  'pre-extract': Database,
  upload: Upload,
  'schema-edit': GitBranch,
  edit: Pencil,
  configure: Settings2,
  transform: Wand2,
  load: Download,
  stats: BarChart3,
}

const PHASE_LABELS: Record<Phase, string> = {
  'pre-extract': 'DB Import',
  upload: 'Upload',
  'schema-edit': 'Schema',
  edit: 'Edit Data',
  configure: 'Configure',
  transform: 'Transform',
  load: 'Load',
  stats: 'Stats',
}

export function Spinner({ size = 'md', label }: { size?: 'sm' | 'md' | 'lg'; label?: string }) {
  const sizes = { sm: 'h-4 w-4', md: 'h-6 w-6', lg: 'h-10 w-10' }
  return (
    <div className="flex flex-col items-center gap-2">
      <Loader2 className={`${sizes[size]} text-primary animate-spin`} />
      {label && <span className="text-xs text-muted-foreground">{label}…</span>}
    </div>
  )
}

function AnimatedCounter({ value, duration = 600 }: { value: number; duration?: number }) {
  const [display, setDisplay] = useState(0)
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const start = display
    const diff = value - start
    if (diff === 0) return
    const steps = Math.min(Math.abs(diff), 20)
    const stepDuration = duration / steps
    let step = 0
    const id = setInterval(() => {
      step++
      const progress = step / steps
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(start + diff * eased))
      if (step >= steps) {
        clearInterval(id)
        setDisplay(value)
      }
    }, stepDuration)
    return () => clearInterval(id)
  }, [value])

  return <span ref={ref}>{display.toLocaleString()}</span>
}

interface DataTableProps {
  columns: string[]
  rows: Record<string, unknown>[]
  maxRows?: number
  onClose?: () => void
  onEdit?: (rowIndex: number, row: Record<string, unknown>) => void
  interactive?: boolean
}

export function DataTable({ columns, rows, maxRows = 50, onClose, onEdit, interactive = false }: DataTableProps) {
  const displayRows = rows.slice(0, maxRows)
  const [selectedRow, setSelectedRow] = useState<number | null>(interactive ? 0 : null)
  const [selectedCol, setSelectedCol] = useState<number | null>(interactive ? 0 : null)

  useEffect(() => {
    if (!interactive || selectedRow === null) return
    const handleKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return

      const key = e.key.toLowerCase()
      if (key === 'arrowup' && selectedRow > 0) {
        e.preventDefault()
        setSelectedRow(selectedRow - 1)
      } else if (key === 'arrowdown' && selectedRow < displayRows.length - 1) {
        e.preventDefault()
        setSelectedRow(selectedRow + 1)
      } else if (key === 'arrowleft' && selectedCol !== null && selectedCol > 0) {
        e.preventDefault()
        setSelectedCol(selectedCol - 1)
      } else if (key === 'arrowright' && selectedCol !== null && selectedCol < columns.length - 1) {
        e.preventDefault()
        setSelectedCol(selectedCol + 1)
      } else if (key === 'e' && selectedRow !== null) {
        e.preventDefault()
        onEdit?.(selectedRow, displayRows[selectedRow])
      } else if (key === 'x' || key === 'escape') {
        e.preventDefault()
        onClose?.()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [interactive, selectedRow, selectedCol, displayRows, columns.length, onClose, onEdit])

  return (
    <div className="flex flex-col gap-2">
      {onClose && (
        <div className="flex justify-end">
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors" title="Close [X]">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}
      <div className="overflow-x-auto rounded-md border border-border bg-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-muted/50 border-b border-border">
              {columns.map((col, idx) => (
                <th key={col} className={`px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider whitespace-nowrap transition-colors
                  ${interactive && selectedCol === idx && selectedRow !== null ? 'bg-primary/20 text-primary' : 'text-primary'}
                `}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row, rowIdx) => (
              <tr key={rowIdx} className={`border-b border-border/40 last:border-0 transition-colors
                ${interactive && selectedRow === rowIdx ? 'bg-accent/20' : 'hover:bg-accent/10'}
              `}>
                {columns.map((col, colIdx) => (
                  <td key={col} className={`px-3 py-2 whitespace-nowrap max-w-[200px] truncate transition-colors
                    ${interactive && selectedRow === rowIdx && selectedCol === colIdx ? 'bg-primary/30 text-primary font-semibold ring-1 ring-primary' : 'text-foreground'}
                  `}>
                    {row[col] === null ? <span className="text-muted-foreground italic">null</span> : String(row[col] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length > maxRows && (
          <div className="px-3 py-2 text-xs text-muted-foreground bg-muted/30 border-t border-border">
            Showing {maxRows} of {rows.length} rows
          </div>
        )}
      </div>
      {interactive && (
        <div className="text-xs text-muted-foreground px-2">
          {selectedRow !== null && `Row ${selectedRow + 1} of ${displayRows.length}`} · ↑↓ navigate rows · ← → navigate columns · <kbd>E</kbd> edit · <kbd>X</kbd> close
        </div>
      )}
    </div>
  )
}

export function ProgressSteps({ current, onNavigate }: { current: Phase; onNavigate: (p: Phase) => void }) {
  const currentIdx = PHASES.indexOf(current)
  const progressValue = ((currentIdx) / (PHASES.length - 1)) * 100

  return (
    <div className="space-y-3">
      <Progress value={progressValue} className="h-2" />
      <div className="flex items-center w-full">
        {PHASES.map((phase, i) => {
          const isCompleted = i < currentIdx
          const isActive = i === currentIdx
          const isClickable = i <= currentIdx
          const Icon = PHASE_ICONS[phase]
          return (
            <button
              key={phase}
              onClick={() => isClickable && onNavigate(phase)}
              disabled={!isClickable}
              className={`flex-1 py-2 text-xs transition-all text-center group flex flex-col items-center gap-1
                ${isActive ? 'text-primary font-semibold' : ''}
                ${isCompleted ? 'text-accent hover:text-accent/80 cursor-pointer' : ''}
                ${!isCompleted && !isActive ? 'text-muted-foreground cursor-default' : ''}
              `}
            >
              <span className={`inline-flex items-center justify-center w-8 h-8 rounded-full transition-all
                ${isActive ? 'bg-primary text-primary-foreground scale-110 shadow-md' :
                  isCompleted ? 'bg-accent/15 text-accent group-hover:bg-accent/25' :
                  'bg-muted text-muted-foreground'}
              `}>
                <Icon className="h-4 w-4" />
              </span>
              <span className="hidden sm:inline">{PHASE_LABELS[phase]}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export function StatCard({ label, value, icon }: { label: string; value: string | number; icon?: React.ReactNode }) {
  const numericValue = typeof value === 'number' ? value : null

  return (
    <div className="rounded-lg border border-border bg-card p-4 text-center hover:border-primary/40 hover:shadow-sm transition-all">
      {icon && <div className="flex justify-center mb-2 text-accent">{icon}</div>}
      <div className="text-2xl font-bold text-primary">
        {numericValue !== null ? <AnimatedCounter value={numericValue} /> : value}
      </div>
      <div className="text-xs text-muted-foreground mt-1 uppercase tracking-wide">{label}</div>
    </div>
  )
}

export function PhaseHeader({ title, description }: { phase?: string; title: string; description: string }) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex-1">
        <h2 className="text-2xl font-bold text-foreground mb-1">{title}</h2>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
    </div>
  )
}

export function EmptyState({ icon, message, sub }: { icon?: React.ReactNode; message: string; sub?: string }) {
  return (
    <div className="text-center py-16">
      {icon && <div className="flex justify-center mb-3 text-muted-foreground/40">{icon}</div>}
      <p className="text-muted-foreground text-sm">{message}</p>
      {sub && <p className="text-xs text-muted-foreground/60 mt-1">{sub}</p>}
    </div>
  )
}

export function LiveTerminal({ lines }: { lines: string[] }) {
  const [visible, setVisible] = useState(0)

  useEffect(() => {
    if (visible >= lines.length) return
    const id = setTimeout(() => setVisible((v) => v + 1), 80)
    return () => clearTimeout(id)
  }, [visible, lines.length])

  return (
    <div className="rounded-md border border-border bg-muted/30 p-3 font-mono text-xs max-h-40 overflow-y-auto">
      {lines.slice(0, visible).map((line, i) => (
        <div key={i} className="text-foreground/80">
          <span className="text-accent mr-2">›</span>{line}
        </div>
      ))}
      {visible < lines.length && (
        <span className="text-primary animate-pulse">▊</span>
      )}
    </div>
  )
}

export function MiniBar({ value, max, color = 'bg-primary' }: { value: number; max: number; color?: string }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0
  return (
    <div className="w-16 h-2 bg-muted rounded-full inline-block align-middle ml-2 overflow-hidden">
      <div className={`h-full ${color} transition-all duration-500`} style={{ width: `${pct}%` }} />
    </div>
  )
}
