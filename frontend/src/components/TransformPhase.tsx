import { useState } from 'react'
import { usePipeline } from '../store/pipeline'
import { transform } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/8bit/card'
import { Button } from '@/components/ui/8bit/button'
import { Badge } from '@/components/ui/8bit/badge'
import { PhaseHeader, StatCard, Spinner, DataTable, LiveTerminal } from './ui'

export default function TransformPhase() {
  const { state, dispatch } = usePipeline()
  const [result, setResult] = useState(state.transformResult)
  const [loading, setLoading] = useState(false)

  const handleTransform = async () => {
    if (!state.sessionId) return
    setLoading(true)
    dispatch({ type: 'SET_ERROR', error: null })
    try {
      const res = await transform(state.sessionId)
      setResult(res)
    } catch (e: unknown) {
      dispatch({ type: 'SET_ERROR', error: e instanceof Error ? e.message : 'Transform failed' })
    } finally {
      setLoading(false)
    }
  }

  const handleContinue = () => {
    if (result) dispatch({ type: 'SET_TRANSFORM', result })
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <PhaseHeader
          phase="transform"
          title="Transform Data"
          description="Apply encoding fixes, type conversions, and null normalization."
        />
        <Button onClick={handleTransform} disabled={loading}>
          {loading ? 'Transforming...' : 'Run Transform'}
        </Button>
      </div>

      {loading && (
        <div className="space-y-4">
          <div className="flex items-center justify-center py-8">
            <Spinner size="lg" label="Transforming records" />
          </div>
          <LiveTerminal lines={[
            'Loading raw tables...',
            'Fixing encoding (latin-1 → utf-8)...',
            'Normalizing null values...',
            'Applying type coercions...',
            'Resolving reference mappings...',
            'Building output tables...',
            'Computing transform statistics...',
          ]} />
        </div>
      )}

      {state.error && <p className="text-destructive text-sm retro pixel-in">! {state.error}</p>}

      {result && !loading && (
        <div className="space-y-4 stagger">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <StatCard label="Tables" value={result.tables_transformed} icon="[ # ]" />
            <StatCard label="Total Rows" value={result.total_rows} icon="[ = ]" />
            <StatCard label="Encoding Fixes" value={result.encoding_conversions} icon="[ A ]" />
            <StatCard label="Type Conversions" value={result.type_conversions} icon="[1.0]" />
            <StatCard label="Ref Mappings" value={result.reference_mappings} icon="[ → ]" />
            <StatCard label="Null Fills" value={result.null_normalizations} icon="[ ø ]" />
          </div>

          {result.warnings.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-xs">Warnings</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-1">
                  {result.warnings.map((w, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs retro">
                      <Badge variant="secondary">warn</Badge>
                      <span className="text-foreground">{w}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {Object.entries(result.preview).map(([table, rows]) => {
            const cols = rows.length > 0 ? Object.keys(rows[0]) : []
            return (
              <Card key={table}>
                <CardHeader>
                  <CardTitle className="text-xs">
                    Preview: {table}
                    <span className="text-primary/40 ml-2">[{rows.length} rows shown]</span>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <DataTable columns={cols} rows={rows} maxRows={5} />
                </CardContent>
              </Card>
            )
          })}

          <div className="flex justify-end">
            <Button onClick={handleContinue}>
              Continue to Load
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
