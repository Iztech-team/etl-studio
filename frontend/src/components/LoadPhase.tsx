import { useState } from 'react'
import { usePipeline } from '../store/pipeline'
import { load, downloadUrl } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/8bit/card'
import { Button } from '@/components/ui/8bit/button'
import { Badge } from '@/components/ui/8bit/badge'
import { Checkbox } from '@/components/ui/8bit/checkbox'
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
          <CardTitle className="text-xs">Output Settings</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div>
              <label className="text-[10px] text-muted-foreground retro uppercase tracking-wider block mb-2">Format</label>
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

            <label className="flex items-center gap-3 text-xs retro text-foreground cursor-pointer">
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

      {state.error && <p className="text-destructive text-sm retro pixel-in">! {state.error}</p>}

      {result && !loading && (
        <div className="space-y-4 stagger">
          <Card>
            <CardContent className="pt-4">
              <div className="flex items-center gap-3 mb-4">
                <Badge variant={result.ok ? 'default' : 'destructive'}>
                  {result.ok ? 'SUCCESS' : 'ERRORS'}
                </Badge>
                {result.transaction_wrapped && <Badge variant="secondary">TX Wrapped</Badge>}
                <span className="text-[10px] retro text-muted-foreground ml-auto">
                  {result.output_files.length} file{result.output_files.length !== 1 ? 's' : ''} generated
                </span>
              </div>

              {result.errors.length > 0 && (
                <div className="mb-4 space-y-1">
                  {result.errors.map((err, i) => (
                    <p key={i} className="text-destructive text-xs retro">! {err}</p>
                  ))}
                </div>
              )}

              <div className="space-y-2">
                {result.output_files.map((fname) => (
                  <div key={fname} className="flex items-center justify-between py-2 border-b border-dashed border-foreground/10 last:border-0 hover:bg-primary/5 px-1 transition-colors">
                    <span className="text-xs retro text-foreground">
                      <span className="text-primary/40 mr-2">{'>'}</span>
                      {fname}
                    </span>
                    <a
                      href={downloadUrl(state.sessionId!, fname)}
                      download
                      className="text-primary text-xs retro hover:underline glow"
                    >
                      [DOWNLOAD]
                    </a>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {Object.keys(result.rows_written).length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-xs">Rows Written</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                  {Object.entries(result.rows_written).map(([table, count]) => (
                    <div key={table} className="text-xs retro py-1">
                      <span className="text-muted-foreground">{table}:</span>{' '}
                      <span className="text-primary glow">{count.toLocaleString()}</span>
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
