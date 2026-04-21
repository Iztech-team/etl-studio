import { useState } from 'react'
import { usePipeline } from '../store/pipeline'
import { validate } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { PhaseHeader, Spinner, LiveTerminal, MiniBar } from './ui'

export default function ValidatePhase() {
  const { state, dispatch } = usePipeline()
  const [result, setResult] = useState(state.validateResult)
  const [loading, setLoading] = useState(false)

  const handleValidate = async () => {
    if (!state.sessionId) return
    setLoading(true)
    dispatch({ type: 'SET_ERROR', error: null })
    try {
      const res = await validate(state.sessionId)
      setResult(res)
    } catch (e: unknown) {
      dispatch({ type: 'SET_ERROR', error: e instanceof Error ? e.message : 'Validation failed' })
    } finally {
      setLoading(false)
    }
  }

  const handleContinue = () => {
    if (result) dispatch({ type: 'SET_VALIDATE', result })
  }

  const totalRecords = result ? Object.values(result.record_counts).reduce((a, b) => a + b, 0) : 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <PhaseHeader
          phase="validate"
          title="Validate Data"
          description="Check for duplicates, truncation risks, and data quality issues."
        />
        <Button onClick={handleValidate} disabled={loading}>
          {loading ? 'Validating...' : 'Run Validation'}
        </Button>
      </div>

      {loading && (
        <div className="space-y-4">
          <div className="flex items-center justify-center py-8">
            <Spinner size="lg" label="Scanning records" />
          </div>
          <LiveTerminal lines={[
            'Initializing validation engine...',
            'Loading extracted tables...',
            'Checking for duplicate rows...',
            'Analyzing column data types...',
            'Scanning for truncation risks...',
            'Computing financial totals...',
          ]} />
        </div>
      )}

      {state.error && <p className="text-destructive text-sm">{state.error}</p>}

      {result && !loading && (
        <div className="space-y-4">
          <Card>
            <CardContent className="pt-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Badge variant={result.passed ? 'default' : 'destructive'}>
                    {result.passed ? 'PASSED' : 'FAILED'}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {result.issues.length} issue{result.issues.length !== 1 ? 's' : ''} found
                  </span>
                </div>
                <span className="text-xs text-muted-foreground">
                  <span className="text-accent font-mono">{totalRecords.toLocaleString()}</span> total records
                </span>
              </div>
            </CardContent>
          </Card>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            {Object.entries(result.record_counts).map(([table, count]) => (
              <Card key={table}>
                <CardContent className="pt-4">
                  <div className="text-2xl font-bold text-primary">{count.toLocaleString()}</div>
                  <div className="text-xs text-muted-foreground mt-1 flex items-center">
                    {table}
                    <MiniBar value={count} max={totalRecords} />
                  </div>
                  {result.duplicate_counts[table] > 0 && (
                    <div className="mt-2">
                      <Badge variant="destructive">{result.duplicate_counts[table]} dups</Badge>
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>

          {result.issues.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">
                  Issues
                  <span className="text-destructive ml-2 font-mono text-xs">[{result.issues.length}]</span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {result.issues.map((issue, i) => (
                    <div key={i} className="flex items-start gap-2 py-1.5 border-b border-border/40 last:border-0 hover:bg-accent/5 px-2 rounded transition-colors">
                      <Badge variant={issue.level === 'error' ? 'destructive' : 'secondary'}>
                        {issue.level}
                      </Badge>
                      <div className="text-xs text-foreground">
                        <span className="text-muted-foreground font-mono">{issue.table}{issue.column ? `.${issue.column}` : ''}</span>
                        <span className="text-accent mx-2">—</span>
                        {issue.message}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {result.truncation_risks.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Truncation Risks</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-1">
                  {result.truncation_risks.map((r, i) => (
                    <div key={i} className="text-xs text-foreground py-1 hover:bg-accent/5 px-2 rounded transition-colors">
                      <span className="text-destructive font-mono">{r.table}.{r.column}</span>
                      <span className="text-accent mx-2">—</span>
                      {r.count} value(s), max {r.max_length} chars
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          <div className="flex justify-end">
            <Button onClick={handleContinue}>
              Continue to Transform
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
