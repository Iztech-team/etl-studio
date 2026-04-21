import { useEffect, useState } from 'react'
import { usePipeline } from '../store/pipeline'
import { fetchStats } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
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
      <div className="text-center py-20">
        <p className="text-muted-foreground">No stats available.</p>
      </div>
    )
  }

  const scoreColor =
    result.quality_score >= 80 ? 'text-primary' :
    result.quality_score >= 50 ? 'text-secondary-foreground' :
    'text-destructive'
  const scoreBg =
    result.quality_score >= 80 ? 'bg-primary' :
    result.quality_score >= 50 ? 'bg-secondary' :
    'bg-destructive'
  const scoreLabel =
    result.quality_score >= 90 ? 'EXCELLENT' :
    result.quality_score >= 80 ? 'GOOD' :
    result.quality_score >= 50 ? 'FAIR' : 'POOR'
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
          <div className="text-center space-y-4">
            <div className="text-xs text-muted-foreground uppercase tracking-wider">Quality Score</div>
            <div className={`text-6xl font-bold ${scoreColor}`}>
              {result.quality_score}
            </div>
            <div className={`text-xs ${scoreColor} uppercase tracking-widest font-semibold`}>
              {scoreLabel}
            </div>
            <div className="max-w-sm mx-auto">
              <Progress value={result.quality_score} className="h-3" progressBg={scoreBg} />
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <StatCard label="Records In" value={result.total_records_in} />
        <StatCard label="Records Out" value={result.total_records_out} />
        <StatCard label="Tables" value={Object.keys(result.tables).length} />
      </div>

      {Object.keys(result.tables).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Per-Table Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
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
                    <tr key={table} className="border-b border-border/40 last:border-0 hover:bg-accent/5 transition-colors">
                      <td className="py-2 px-2 text-foreground font-mono">
                        {table}
                      </td>
                      <td className="py-2 px-2 text-right text-muted-foreground">{stats.rows_in.toLocaleString()}</td>
                      <td className="py-2 px-2 text-right text-primary font-semibold">{stats.rows_out.toLocaleString()}</td>
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

      <div className="text-center pt-4 space-y-4">
        <p className="text-sm text-muted-foreground">Pipeline complete.</p>
        <Button variant="outline" onClick={handleReset}>
          Start Over
        </Button>
      </div>
    </div>
  )
}
