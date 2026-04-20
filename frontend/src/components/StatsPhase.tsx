import { useEffect, useState } from 'react'
import { usePipeline } from '../store/pipeline'
import { fetchStats } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/8bit/card'
import { Button } from '@/components/ui/8bit/button'
import { Badge } from '@/components/ui/8bit/badge'
import { Progress } from '@/components/ui/8bit/progress'
import { PhaseHeader, StatCard, Spinner, MiniBar } from './ui'

export default function StatsPhase() {
  const { state, dispatch } = usePipeline()
  const [result, setResult] = useState(state.statsResult)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!state.sessionId || result) return
    setLoading(true)
    fetchStats(state.sessionId)
      .then(setResult)
      .catch((e) => dispatch({ type: 'SET_ERROR', error: e instanceof Error ? e.message : 'Failed to load stats' }))
      .finally(() => setLoading(false))
  }, [state.sessionId, result, dispatch])

  const handleReset = () => dispatch({ type: 'RESET' })

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner size="lg" label="Loading stats" />
      </div>
    )
  }

  if (!result) {
    return (
      <div className="text-center py-20 pixel-in">
        <pre className="text-primary/20 text-xs retro leading-tight mx-auto w-fit mb-4">
{`  ┌───────┐
  │  ???  │
  └───────┘`}
        </pre>
        <p className="text-muted-foreground retro text-sm">No stats available.</p>
      </div>
    )
  }

  const scoreColor = result.quality_score >= 80 ? 'text-primary' : result.quality_score >= 50 ? 'text-ember' : 'text-destructive'
  const scoreBg = result.quality_score >= 80 ? 'bg-primary' : result.quality_score >= 50 ? 'bg-ember' : 'bg-destructive'
  const scoreLabel = result.quality_score >= 90 ? 'EXCELLENT' : result.quality_score >= 80 ? 'GOOD' : result.quality_score >= 50 ? 'FAIR' : 'POOR'
  const maxRowsIn = Math.max(...Object.values(result.tables).map((t) => t.rows_in), 1)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <PhaseHeader
          phase="stats"
          title="Pipeline Stats"
          description="Summary of the completed ETL pipeline run."
        />
        <Badge>{result.pipeline_stage.toUpperCase()}</Badge>
      </div>

      <Card>
        <CardContent className="py-8">
          <div className="text-center space-y-4 pixel-in">
            <div className="text-[10px] retro text-muted-foreground uppercase tracking-wider">Quality Score</div>
            <div className={`text-6xl retro font-bold ${scoreColor} glow`}>
              {result.quality_score}
            </div>
            <div className={`text-[10px] retro ${scoreColor} uppercase tracking-widest`}>
              {'[ '}{scoreLabel}{' ]'}
            </div>
            <div className="max-w-sm mx-auto">
              <Progress
                value={result.quality_score}
                variant="retro"
                className="h-5"
                progressBg={scoreBg}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 stagger">
        <StatCard label="Records In" value={result.total_records_in} icon="[ > ]" />
        <StatCard label="Records Out" value={result.total_records_out} icon="[ < ]" />
        <StatCard label="Tables" value={Object.keys(result.tables).length} icon="[ # ]" />
      </div>

      {Object.keys(result.tables).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xs">Per-Table Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-xs retro">
                <thead>
                  <tr className="text-[10px] text-muted-foreground uppercase tracking-wider border-b-4 border-dashed border-foreground/20">
                    <th className="text-left py-2 px-2">Table</th>
                    <th className="text-right py-2 px-2">In</th>
                    <th className="text-right py-2 px-2">Out</th>
                    <th className="text-right py-2 px-2">Cols</th>
                    <th className="text-right py-2 px-2">Dups</th>
                    <th className="text-right py-2 px-2">Size</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(result.tables).map(([table, stats]) => (
                    <tr key={table} className="border-b border-dashed border-foreground/10 hover:bg-primary/5 transition-colors">
                      <td className="py-2 px-2 text-foreground">
                        <span className="text-primary/30 mr-1">{'>'}</span>
                        {table}
                      </td>
                      <td className="py-2 px-2 text-right text-muted-foreground">{stats.rows_in.toLocaleString()}</td>
                      <td className="py-2 px-2 text-right text-primary glow">{stats.rows_out.toLocaleString()}</td>
                      <td className="py-2 px-2 text-right text-muted-foreground">{stats.columns}</td>
                      <td className="py-2 px-2 text-right">
                        {stats.duplicates > 0 ? (
                          <Badge variant="destructive">{stats.duplicates}</Badge>
                        ) : (
                          <span className="text-muted-foreground">0</span>
                        )}
                      </td>
                      <td className="py-2 px-2 text-right">
                        <MiniBar value={stats.rows_in} max={maxRowsIn} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="text-center pt-4 space-y-4 pixel-in">
        <pre className="text-primary/20 text-[10px] retro leading-tight mx-auto w-fit select-none">
{`  ╔══════════════════╗
  ║  PIPELINE DONE!  ║
  ╚══════════════════╝`}
        </pre>
        <Button variant="outline" onClick={handleReset}>
          Start Over
        </Button>
      </div>
    </div>
  )
}
