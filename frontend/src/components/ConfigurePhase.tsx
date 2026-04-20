import { useState } from 'react'
import { usePipeline } from '../store/pipeline'
import { configure } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/8bit/card'
import { Button } from '@/components/ui/8bit/button'
import { Input } from '@/components/ui/8bit/input'
import { Checkbox } from '@/components/ui/8bit/checkbox'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/8bit/select'
import { PhaseHeader } from './ui'
import type { TableConfig, ColumnConfig } from '../types/api'

const DATA_TYPES = ['string', 'integer', 'float', 'boolean', 'date'] as const

export default function ConfigurePhase() {
  const { state, dispatch } = usePipeline()
  const schema = state.uploadResult?.inferred_schema ?? {}

  const [nullValues, setNullValues] = useState('NULL, null, N/A, n/a')
  const [tableConfigs, setTableConfigs] = useState<Record<string, ColumnConfig[]>>(() => {
    const configs: Record<string, ColumnConfig[]> = {}
    for (const [table, cols] of Object.entries(schema)) {
      configs[table] = Object.entries(cols).map(([name, info]) => ({
        name,
        target_name: name,
        data_type: info.inferred_type,
        nullable: info.nullable,
        include: true,
      }))
    }
    return configs
  })

  const totalCols = Object.values(tableConfigs).reduce((a, cols) => a + cols.length, 0)
  const includedCols = Object.values(tableConfigs).reduce((a, cols) => a + cols.filter(c => c.include).length, 0)

  const updateColumn = (table: string, colIdx: number, patch: Partial<ColumnConfig>) => {
    setTableConfigs((prev) => ({
      ...prev,
      [table]: prev[table].map((c, i) => (i === colIdx ? { ...c, ...patch } : c)),
    }))
  }

  const handleSave = async () => {
    if (!state.sessionId) return
    dispatch({ type: 'SET_LOADING', loading: true })
    try {
      const tables: TableConfig[] = Object.entries(tableConfigs).map(([source_table, columns]) => ({
        source_table,
        columns,
        load_order: 0,
      }))
      const result = await configure(state.sessionId, {
        tables,
        encoding: 'utf-8',
        null_values: nullValues.split(',').map((s) => s.trim()),
      })
      dispatch({ type: 'SET_CONFIGURE', result })
    } catch (e: unknown) {
      dispatch({ type: 'SET_ERROR', error: e instanceof Error ? e.message : 'Configuration failed' })
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <PhaseHeader
          phase="configure"
          title="Configure Mappings"
          description="Set column mappings, types, and null value handling."
        />
        <span className="text-[10px] retro text-muted-foreground hidden sm:inline">
          {includedCols}/{totalCols} columns
        </span>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-xs">Null Values</CardTitle>
        </CardHeader>
        <CardContent>
          <Input
            type="text"
            value={nullValues}
            onChange={(e) => setNullValues(e.target.value)}
            placeholder="Comma-separated null values"
          />
          <p className="text-[10px] text-muted-foreground mt-2 retro">
            <span className="text-primary/40">// </span>
            Comma-separated values to treat as null
          </p>
        </CardContent>
      </Card>

      <div className="space-y-4 stagger">
        {Object.entries(tableConfigs).map(([table, columns]) => {
          const included = columns.filter(c => c.include).length
          return (
            <Card key={table}>
              <CardHeader>
                <CardTitle className="text-xs">
                  {table}
                  <span className="text-primary/40 ml-2">[{included}/{columns.length} cols]</span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs retro">
                    <thead>
                      <tr className="text-[10px] text-muted-foreground uppercase tracking-wider border-b-4 border-dashed border-foreground/20">
                        <th className="text-left py-2 px-2">Inc</th>
                        <th className="text-left py-2 px-2">Source</th>
                        <th className="text-left py-2 px-2">Target</th>
                        <th className="text-left py-2 px-2">Type</th>
                      </tr>
                    </thead>
                    <tbody>
                      {columns.map((col, i) => (
                        <tr key={col.name} className={`border-b border-dashed border-foreground/10 hover:bg-primary/5 transition-colors ${!col.include ? 'opacity-40' : ''}`}>
                          <td className="py-2 px-2">
                            <Checkbox
                              checked={col.include}
                              onCheckedChange={(checked) => updateColumn(table, i, { include: !!checked })}
                            />
                          </td>
                          <td className="py-2 px-2 text-muted-foreground">
                            <span className="text-primary/20 mr-1">{'>'}</span>
                            {col.name}
                          </td>
                          <td className="py-2 px-2">
                            <Input
                              type="text"
                              value={col.target_name ?? col.name}
                              onChange={(e) => updateColumn(table, i, { target_name: e.target.value })}
                              className="text-[10px]"
                            />
                          </td>
                          <td className="py-2 px-2">
                            <Select
                              value={col.data_type}
                              onValueChange={(val) => updateColumn(table, i, { data_type: val })}
                            >
                              <SelectTrigger className="w-[120px]">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {DATA_TYPES.map((t) => (
                                  <SelectItem key={t} value={t}>{t}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <div className="flex justify-end">
        <Button onClick={handleSave} disabled={state.loading}>
          {state.loading ? 'Saving...' : 'Save & Validate'}
        </Button>
      </div>

      {state.error && (
        <p className="text-destructive text-sm retro pixel-in">! {state.error}</p>
      )}
    </div>
  )
}
