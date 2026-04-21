import { useState } from 'react'
import { Hash, Rows, Languages, Type, ArrowRightLeft, CircleSlash } from 'lucide-react'
import { usePipeline } from '../store/pipeline'
import { transform } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
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

      {state.error && <p className="text-destructive text-sm">{state.error}</p>}

      {result && !loading && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <StatCard label="Tables" value={result.tables_transformed} icon={<Hash className="h-5 w-5" />} />
            <StatCard label="Total Rows" value={result.total_rows} icon={<Rows className="h-5 w-5" />} />
            <StatCard label="Encoding Fixes" value={result.encoding_conversions} icon={<Languages className="h-5 w-5" />} />
            <StatCard label="Type Conversions" value={result.type_conversions} icon={<Type className="h-5 w-5" />} />
            <StatCard label="Ref Mappings" value={result.reference_mappings} icon={<ArrowRightLeft className="h-5 w-5" />} />
            <StatCard label="Null Fills" value={result.null_normalizations} icon={<CircleSlash className="h-5 w-5" />} />
          </div>

          {result.warnings.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Warnings</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-1">
                  {result.warnings.map((w, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
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
                  <CardTitle className="text-sm">
                    Preview: <span className="text-primary">{table}</span>
                    <span className="text-accent ml-2 font-mono text-xs">[{rows.length} shown]</span>
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
