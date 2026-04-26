import { useState, useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { usePipeline } from '../store/pipeline'
import { configure, uploadDDL, applyDDL } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import { PhaseHeader } from './ui'
import type { TableConfig, ColumnConfig, ColumnSchema } from '../types/api'

const DATA_TYPES = ['string', 'integer', 'float', 'boolean', 'date'] as const

export default function ConfigurePhase() {
  const { state, dispatch } = usePipeline()
  const schema = state.uploadResult?.inferred_schema ?? {}

  // Get schema edit state for applying renames
  const droppedTables = state.schemaEditState?.droppedTables ?? new Set()
  const renamedTables = state.schemaEditState?.renamedTables ?? new Map()
  const renamedColumns = state.schemaEditState?.renamedColumns ?? new Map()

  const [nullValues, setNullValues] = useState('NULL, null, N/A, n/a')
  const [tableConfigs, setTableConfigs] = useState<Record<string, ColumnConfig[]>>(() => {
    const configs: Record<string, ColumnConfig[]> = {}
    for (const [table, cols] of Object.entries(schema)) {
      // Skip dropped tables
      if (droppedTables.has(table)) continue

      const tableRenamedColumns = renamedColumns.get(table) || new Map()
      configs[table] = Object.entries(cols).map(([name, info]) => {
        // Apply column renames from schema edit
        const targetName = tableRenamedColumns.get(name) || name
        return {
          name,
          target_name: targetName,
          data_type: info.inferred_type,
          nullable: info.nullable,
          include: true,
        }
      })
    }
    return configs
  })

  const [ddlSchema, setDdlSchema] = useState<Record<string, Record<string, ColumnSchema>>>(
    () => state.uploadResult?.ddl_schema ?? {}
  )
  const [matchingTables, setMatchingTables] = useState<string[]>(() => {
    const ddl = state.uploadResult?.ddl_schema ?? {}
    return Object.keys(ddl).filter((t) => t in schema)
  })
  const [selectedDdlTables, setSelectedDdlTables] = useState<Set<string>>(new Set())
  const [appliedDdlTables, setAppliedDdlTables] = useState<Set<string>>(new Set())
  const [ddlError, setDdlError] = useState<string | null>(null)
  const [ddlApplyResults, setDdlApplyResults] = useState<{ table: string; applied: boolean; errors: string[] }[]>([])

  const onDdlDrop = useCallback(async (accepted: File[]) => {
    if (accepted.length === 0 || !state.sessionId) return
    setDdlError(null)
    try {
      const result = await uploadDDL(state.sessionId, accepted)
      setDdlSchema(result.ddl_schema)
      setMatchingTables(result.matching_tables)
      setSelectedDdlTables(new Set())
      setDdlApplyResults([])
    } catch (e: unknown) {
      setDdlError(e instanceof Error ? e.message : 'DDL upload failed')
    }
  }, [state.sessionId])

  const { getRootProps: getDdlRootProps, getInputProps: getDdlInputProps, isDragActive: isDdlDragActive } = useDropzone({
    onDrop: onDdlDrop,
    accept: {
      'application/sql': ['.sql'],
      'text/plain': ['.sql'],
    },
  })

  const toggleDdlTable = (table: string) => {
    setSelectedDdlTables((prev) => {
      const next = new Set(prev)
      if (next.has(table)) next.delete(table)
      else next.add(table)
      return next
    })
  }

  const handleApplyDdl = async () => {
    if (!state.sessionId || selectedDdlTables.size === 0) return
    setDdlError(null)
    try {
      const result = await applyDDL(state.sessionId, [...selectedDdlTables])
      setDdlApplyResults(result.results)
      const applied = new Set(appliedDdlTables)
      for (const r of result.results) {
        if (r.applied) {
          applied.add(r.table)
          const ddlCols = ddlSchema[r.table]
          if (ddlCols) {
            setTableConfigs((prev) => ({
              ...prev,
              [r.table]: prev[r.table].map((col) => {
                const ddlCol = Object.entries(ddlCols).find(
                  ([name]) => name.toLowerCase() === col.name.toLowerCase()
                )
                if (ddlCol) {
                  return {
                    ...col,
                    data_type: ddlCol[1].inferred_type,
                    nullable: ddlCol[1].nullable,
                  }
                }
                return col
              }),
            }))
          }
        }
      }
      setAppliedDdlTables(applied)
      setSelectedDdlTables(new Set())
    } catch (e: unknown) {
      setDdlError(e instanceof Error ? e.message : 'Apply DDL failed')
    }
  }

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
        <span className="text-xs text-muted-foreground hidden sm:inline">
          <span className="text-accent font-mono">{includedCols}</span>/{totalCols} columns
        </span>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Null Values</CardTitle>
        </CardHeader>
        <CardContent>
          <Input
            type="text"
            value={nullValues}
            onChange={(e) => setNullValues(e.target.value)}
            placeholder="Comma-separated null values"
          />
          <p className="text-xs text-muted-foreground mt-2">
            Comma-separated values to treat as null.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">
            DDL Schema
            {appliedDdlTables.size > 0 && (
              <span className="text-accent ml-2 font-mono text-xs">[{appliedDdlTables.size} applied]</span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div
            {...getDdlRootProps()}
            className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-all
              ${isDdlDragActive ? 'border-primary bg-primary/5' : 'border-border hover:bg-accent/5'}
            `}
          >
            <input {...getDdlInputProps()} />
            <p className="text-muted-foreground text-xs">
              {isDdlDragActive ? 'Drop DDL files here...' : 'Drop .sql DDL files here, or click to browse'}
            </p>
          </div>

          {ddlError && (
            <p className="text-destructive text-xs">{ddlError}</p>
          )}

          {matchingTables.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                DDL definitions match these data tables. Select which to apply:
              </p>
              {matchingTables.map((table) => (
                <div key={table} className="flex items-center gap-2 text-sm py-1">
                  <Checkbox
                    checked={selectedDdlTables.has(table) || appliedDdlTables.has(table)}
                    disabled={appliedDdlTables.has(table)}
                    onCheckedChange={() => toggleDdlTable(table)}
                  />
                  <span className="font-mono text-xs">{table}</span>
                  {appliedDdlTables.has(table) && (
                    <span className="text-xs text-primary/60 ml-1">[DDL applied]</span>
                  )}
                </div>
              ))}
              {selectedDdlTables.size > 0 && (
                <Button onClick={handleApplyDdl} size="sm" className="mt-2">
                  Apply DDL ({selectedDdlTables.size})
                </Button>
              )}
            </div>
          )}

          {Object.keys(ddlSchema).length > 0 && matchingTables.length === 0 && (
            <p className="text-xs text-muted-foreground">
              DDL loaded but no table names match the uploaded data.
            </p>
          )}

          {ddlApplyResults.length > 0 && (
            <div className="space-y-1">
              {ddlApplyResults.map((r) => (
                <div key={r.table} className="text-xs">
                  {r.applied ? (
                    <span className="text-primary">{`> ${r.table}: DDL schema applied`}</span>
                  ) : (
                    <div>
                      <span className="text-destructive">{`! ${r.table}: failed`}</span>
                      {r.errors.map((err, i) => (
                        <p key={i} className="text-destructive/70 ml-4">{err}</p>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="space-y-4">
        {Object.entries(tableConfigs).map(([table, columns]) => {
          // Skip dropped tables in display
          if (droppedTables.has(table)) return null

          const included = columns.filter(c => c.include).length
          const displayTableName = renamedTables.get(table) || table
          return (
            <Card key={table}>
              <CardHeader>
                <CardTitle className="text-sm">
                  <span className="text-primary">{displayTableName}</span>
                  {table !== displayTableName && (
                    <span className="text-muted-foreground text-xs ml-2">({table})</span>
                  )}
                  <span className="text-accent ml-2 font-mono text-xs">[{included}/{columns.length}]</span>
                  {appliedDdlTables.has(table) && (
                    <span className="text-xs text-primary/60 ml-2">[DDL]</span>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                        <th className="text-left py-2 px-2">Inc</th>
                        <th className="text-left py-2 px-2">Source</th>
                        <th className="text-left py-2 px-2">Target</th>
                        <th className="text-left py-2 px-2">Type</th>
                      </tr>
                    </thead>
                    <tbody>
                      {columns.map((col, i) => (
                        <tr key={col.name} className={`border-b border-border/40 last:border-0 hover:bg-accent/5 transition-colors ${!col.include ? 'opacity-40' : ''}`}>
                          <td className="py-2 px-2">
                            <Checkbox
                              checked={col.include}
                              onCheckedChange={(checked) => updateColumn(table, i, { include: !!checked })}
                            />
                          </td>
                          <td className="py-2 px-2 text-muted-foreground font-mono text-xs">
                            {col.name}
                          </td>
                          <td className="py-2 px-2">
                            <Input
                              type="text"
                              value={col.target_name ?? col.name}
                              onChange={(e) => updateColumn(table, i, { target_name: e.target.value })}
                              className="h-8 text-xs"
                            />
                          </td>
                          <td className="py-2 px-2">
                            <div className="flex items-center gap-2">
                              <Select
                                value={col.data_type}
                                onValueChange={(val) => updateColumn(table, i, { data_type: val })}
                              >
                                <SelectTrigger className="w-[120px] h-8 text-xs">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  {DATA_TYPES.map((t) => (
                                    <SelectItem key={t} value={t}>{t}</SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                              {appliedDdlTables.has(table) && ddlSchema[table]?.[col.name]?.original_type && (
                                <span className="text-[10px] text-muted-foreground">
                                  ({ddlSchema[table][col.name].original_type})
                                </span>
                              )}
                            </div>
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
        <p className="text-destructive text-sm">{state.error}</p>
      )}
    </div>
  )
}
