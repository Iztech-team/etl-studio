import { useState } from 'react'
import { Download } from 'lucide-react'
import { usePipeline } from '../store/pipeline'
import { load, downloadUrl } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { PhaseHeader, Spinner, LiveTerminal } from './ui'
import type { LoadRequest } from '../types/api'

export default function LoadPhase() {
  const { state, dispatch } = usePipeline()
  const [format, setFormat] = useState<'json' | 'sql'>('json')
  const [fkOrder, setFkOrder] = useState(true)
  const [result, setResult] = useState(state.loadResult)
  const [loading, setLoading] = useState(false)

  const handleLoad = async () => {
    if (!state.sessionId) return
    setLoading(true)
    dispatch({ type: 'SET_ERROR', error: null })
    try {
      const config: LoadRequest = {
        output_format: format,
        use_staging: false,
        respect_fk_order: fkOrder,
      }
      const res = await load(state.sessionId, config)
      setResult(res)
    } catch (e: unknown) {
      dispatch({ type: 'SET_ERROR', error: e instanceof Error ? e.message : 'Load failed' })
    } finally {
      setLoading(false)
    }
  }

  const handleContinue = () => {
    if (result) dispatch({ type: 'SET_LOAD', result })
  }

  return (
    <div className="space-y-6">
      <PhaseHeader
        phase="load"
        title="Load & Export"
        description="Choose output format and generate downloadable files."
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Output Settings</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div>
              <label className="text-xs text-muted-foreground uppercase tracking-wider block mb-2">Format</label>
              <div className="flex gap-3">
                {(['json', 'sql'] as const).map((f) => (
                  <Button
                    key={f}
                    variant={format === f ? 'default' : 'outline'}
                    onClick={() => setFormat(f)}
                  >
                    {f.toUpperCase()}
                  </Button>
                ))}
              </div>
            </div>

            <label className="flex items-center gap-3 text-sm text-foreground cursor-pointer">
              <Checkbox
                checked={fkOrder}
                onCheckedChange={(checked) => setFkOrder(!!checked)}
              />
              Respect FK ordering
            </label>
          </div>
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button onClick={handleLoad} disabled={loading}>
          {loading ? 'Generating...' : 'Generate Output'}
        </Button>
      </div>

      {loading && (
        <div className="space-y-4">
          <div className="flex items-center justify-center py-8">
            <Spinner size="lg" label={`Writing ${format.toUpperCase()}`} />
          </div>
          <LiveTerminal lines={
            format === 'sql'
              ? ['BEGIN;', 'Sorting tables by FK order...', 'Writing INSERT statements...', 'COMMIT;', 'Saving dump.sql...']
              : ['Serializing tables to JSON...', 'Writing per-table files...', 'Writing all_tables.json...', 'Done.']
          } />
        </div>
      )}

      {state.error && <p className="text-destructive text-sm">{state.error}</p>}

      {result && !loading && (
        <div className="space-y-4">
          <Card>
            <CardContent className="pt-4">
              <div className="flex items-center gap-3 mb-4">
                <Badge variant={result.ok ? 'default' : 'destructive'}>
                  {result.ok ? 'SUCCESS' : 'ERRORS'}
                </Badge>
                {result.transaction_wrapped && <Badge variant="secondary">TX Wrapped</Badge>}
                <span className="text-xs text-muted-foreground ml-auto">
                  {result.output_files.length} file{result.output_files.length !== 1 ? 's' : ''} generated
                </span>
              </div>

              {result.errors.length > 0 && (
                <div className="mb-4 space-y-1">
                  {result.errors.map((err, i) => (
                    <p key={i} className="text-destructive text-xs">{err}</p>
                  ))}
                </div>
              )}

              <div className="space-y-2">
                {result.output_files.map((fname) => (
                  <div key={fname} className="flex items-center justify-between py-2 border-b border-border/40 last:border-0 hover:bg-accent/5 px-2 rounded transition-colors">
                    <span className="text-sm text-foreground font-mono">
                      {fname}
                    </span>
                    <a
                      href={downloadUrl(state.sessionId!, fname)}
                      download
                      className="inline-flex items-center gap-1 text-primary text-xs font-semibold hover:underline"
                    >
                      <Download className="h-3 w-3" /> Download
                    </a>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {Object.keys(result.rows_written).length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Rows Written</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                  {Object.entries(result.rows_written).map(([table, count]) => (
                    <div key={table} className="text-xs py-1">
                      <span className="text-muted-foreground font-mono">{table}:</span>{' '}
                      <span className="text-primary font-semibold">{count.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          <div className="flex justify-end">
            <Button onClick={handleContinue}>
              View Stats
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
