import { useEffect, useRef, useState, type ReactNode } from 'react'
import { PHASES, type Phase } from '../../store/pipeline'
import { Progress } from '@/components/ui/8bit/progress'

/* ------------------------------------------------------------------ */
/*  Pixel Art Icons (inline SVG-like, using divs)                     */
/* ------------------------------------------------------------------ */
const PHASE_ICONS: Record<Phase, string> = {
  upload:    '[ ^ ]',
  configure: '[ # ]',
  validate:  '[ ? ]',
  transform: '[ ~ ]',
  load:      '[ > ]',
  stats:     '[ * ]',
}

/* ------------------------------------------------------------------ */
/*  Spinner (8-bit style)                                             */
/* ------------------------------------------------------------------ */
export function Spinner({ size = 'md', label }: { size?: 'sm' | 'md' | 'lg'; label?: string }) {
  const sizes = { sm: 'h-4 w-4', md: 'h-6 w-6', lg: 'h-10 w-10' }
  const [frame, setFrame] = useState(0)
  const frames = ['|', '/', '-', '\\']

  useEffect(() => {
    const id = setInterval(() => setFrame((f) => (f + 1) % 4), 150)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="flex flex-col items-center gap-2">
      <div className={`${sizes[size]} flex items-center justify-center`}>
        <span className="retro text-primary text-2xl glow">{frames[frame]}</span>
      </div>
      {label && (
        <span className="text-[10px] retro text-muted-foreground">
          {label}<span className="blink">_</span>
        </span>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  AnimatedCounter                                                   */
/* ------------------------------------------------------------------ */
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
        ref.current?.classList.add('count-pop')
        setTimeout(() => ref.current?.classList.remove('count-pop'), 300)
      }
    }, stepDuration)
    return () => clearInterval(id)
  }, [value])

  return <span ref={ref}>{display.toLocaleString()}</span>
}

/* ------------------------------------------------------------------ */
/*  DataTable                                                         */
/* ------------------------------------------------------------------ */
interface DataTableProps {
  columns: string[]
  rows: Record<string, unknown>[]
  maxRows?: number
}

export function DataTable({ columns, rows, maxRows = 50 }: DataTableProps) {
  const displayRows = rows.slice(0, maxRows)
  return (
    <div className="overflow-x-auto relative border-y-6 border-foreground dark:border-ring pixel-in">
      <table className="w-full text-sm retro">
        <thead>
          <tr className="bg-card border-b-4 border-dashed border-foreground dark:border-ring">
            {columns.map((col) => (
              <th key={col} className="px-3 py-2 text-left text-[10px] text-primary uppercase tracking-wider whitespace-nowrap">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {displayRows.map((row, i) => (
            <tr key={i} className="border-b-4 border-dashed border-foreground/20 dark:border-ring/20 hover:bg-primary/5 transition-colors">
              {columns.map((col) => (
                <td key={col} className="px-3 py-1.5 text-foreground whitespace-nowrap max-w-[200px] truncate text-[10px]">
                  {row[col] === null ? <span className="text-muted-foreground italic">null</span> : String(row[col] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div
        className="absolute inset-0 border-x-6 -mx-1.5 border-foreground dark:border-ring pointer-events-none"
        aria-hidden="true"
      />
      {rows.length > maxRows && (
        <div className="px-3 py-1.5 text-[10px] text-muted-foreground bg-card retro">
          Showing {maxRows} of {rows.length} rows
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  ProgressSteps                                                     */
/* ------------------------------------------------------------------ */
const PHASE_LABELS: Record<Phase, string> = {
  upload: 'Upload',
  configure: 'Configure',
  validate: 'Validate',
  transform: 'Transform',
  load: 'Load',
  stats: 'Stats',
}

export function ProgressSteps({ current, onNavigate }: { current: Phase; onNavigate: (p: Phase) => void }) {
  const currentIdx = PHASES.indexOf(current)
  const progressValue = ((currentIdx) / (PHASES.length - 1)) * 100

  return (
    <div className="space-y-3">
      <Progress value={progressValue} variant="retro" className="h-3" />
      <div className="flex items-center w-full">
        {PHASES.map((phase, i) => {
          const isCompleted = i < currentIdx
          const isActive = i === currentIdx
          const isClickable = i <= currentIdx
          return (
            <button
              key={phase}
              onClick={() => isClickable && onNavigate(phase)}
              disabled={!isClickable}
              className={`flex-1 py-2 text-[10px] retro transition-all text-center group
                ${isActive ? 'text-primary' : ''}
                ${isCompleted ? 'text-primary/70 hover:text-primary cursor-pointer' : ''}
                ${!isCompleted && !isActive ? 'text-muted-foreground cursor-default' : ''}
              `}
            >
              <span className={`inline-block w-7 h-7 leading-7 text-[9px] mb-1 transition-all
                ${isActive ? 'bg-primary text-primary-foreground glow scale-110' :
                  isCompleted ? 'bg-primary/20 text-primary group-hover:bg-primary/30' :
                  'bg-muted text-muted-foreground'}
              `}>
                {isCompleted ? '✓' : PHASE_ICONS[phase]}
              </span>
              <br />
              <span className="hidden sm:inline">{PHASE_LABELS[phase]}</span>
              {isActive && <span className="blink hidden sm:inline text-primary">_</span>}
            </button>
          )
        })}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  StatCard (animated)                                               */
/* ------------------------------------------------------------------ */
export function StatCard({ label, value, icon }: { label: string; value: string | number; icon?: string }) {
  const numericValue = typeof value === 'number' ? value : null

  return (
    <div className="relative bg-card border-y-6 border-foreground dark:border-ring p-4 text-center pixel-in hover:bg-primary/5 transition-colors group">
      {icon && <div className="text-lg mb-1 opacity-40 group-hover:opacity-70 transition-opacity">{icon}</div>}
      <div className="text-2xl retro text-primary font-bold glow">
        {numericValue !== null ? <AnimatedCounter value={numericValue} /> : value}
      </div>
      <div className="text-[10px] text-muted-foreground mt-2 retro uppercase tracking-wider">{label}</div>
      <div
        className="absolute inset-0 border-x-6 -mx-1.5 border-foreground dark:border-ring pointer-events-none"
        aria-hidden="true"
      />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  PhaseHeader (title + description + ASCII art)                     */
/* ------------------------------------------------------------------ */
const PHASE_ART: Record<string, string> = {
  upload:    '  ╔═══╗\n  ║ ↑ ║\n  ╚═══╝',
  configure: '  ┌─┬─┐\n  │#│#│\n  └─┴─┘',
  validate:  '  ╔═══╗\n  ║ ✓ ║\n  ╚═══╝',
  transform: '  ┌───┐\n  │ ~ │\n  └───┘',
  load:      '  ╔═══╗\n  ║ ▼ ║\n  ╚═══╝',
  stats:     '  ┌───┐\n  │ ★ │\n  └───┘',
}

export function PhaseHeader({ phase, title, description }: { phase: string; title: string; description: string }) {
  return (
    <div className="flex items-start gap-4 pixel-in">
      <pre className="text-primary/30 text-[10px] retro leading-tight hidden md:block select-none">
        {PHASE_ART[phase] ?? ''}
      </pre>
      <div className="flex-1">
        <h2 className="text-lg retro text-primary mb-1 glow">{title}</h2>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  EmptyState                                                        */
/* ------------------------------------------------------------------ */
export function EmptyState({ icon, message, sub }: { icon: string; message: string; sub?: string }) {
  return (
    <div className="text-center py-16 pixel-in">
      <div className="text-4xl mb-3 opacity-20">{icon}</div>
      <p className="retro text-muted-foreground text-sm">{message}</p>
      {sub && <p className="text-[10px] text-muted-foreground/50 mt-1 retro">{sub}</p>}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  FloatingPixels (ambient decoration)                               */
/* ------------------------------------------------------------------ */
export function FloatingPixels() {
  const [pixels] = useState(() =>
    Array.from({ length: 12 }, (_, i) => ({
      id: i,
      left: Math.random() * 100,
      delay: Math.random() * 8,
      duration: 4 + Math.random() * 6,
      size: 2 + Math.random() * 3,
    }))
  )

  return (
    <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden" aria-hidden="true">
      {pixels.map((p) => (
        <div
          key={p.id}
          className="absolute bottom-0 bg-primary/10"
          style={{
            left: `${p.left}%`,
            width: p.size,
            height: p.size,
            animation: `float-up ${p.duration}s linear ${p.delay}s infinite`,
          }}
        />
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  LiveTerminal (typewriter log output)                              */
/* ------------------------------------------------------------------ */
export function LiveTerminal({ lines }: { lines: string[] }) {
  const [visible, setVisible] = useState(0)

  useEffect(() => {
    if (visible >= lines.length) return
    const id = setTimeout(() => setVisible((v) => v + 1), 80)
    return () => clearTimeout(id)
  }, [visible, lines.length])

  return (
    <div className="bg-background border-y-6 border-foreground dark:border-ring p-3 relative font-mono text-[10px] max-h-40 overflow-y-auto">
      {lines.slice(0, visible).map((line, i) => (
        <div key={i} className="text-primary/80 pixel-in">
          <span className="text-muted-foreground mr-1">&gt;</span>{line}
        </div>
      ))}
      {visible < lines.length && (
        <span className="text-primary blink">_</span>
      )}
      <div className="absolute inset-0 border-x-6 -mx-1.5 border-foreground dark:border-ring pointer-events-none" aria-hidden="true" />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  MiniBar (tiny inline bar chart)                                   */
/* ------------------------------------------------------------------ */
export function MiniBar({ value, max, color = 'bg-primary' }: { value: number; max: number; color?: string }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0
  return (
    <div className="w-16 h-2 bg-muted inline-block align-middle ml-2">
      <div className={`h-full ${color} transition-all duration-500`} style={{ width: `${pct}%` }} />
    </div>
  )
}
