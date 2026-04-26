import { useState, useEffect, useCallback } from 'react'
import { Plus, Trash2, AlertCircle } from 'lucide-react'
import { usePipeline } from '../store/pipeline'
import { fetchTableData, saveTableData } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PhaseHeader, Spinner } from './ui'
import type { ColumnSchema } from '../types/api'

type Row = Record<string, unknown>

interface CellError {
  message: string
}

function validateCell(
  value: unknown,
  colName: string,
  schema: Record<string, ColumnSchema>,
): CellError | null {
  const colSchema = schema[colName]
  if (!colSchema) return null

  const strVal = value === null || value === undefined ? '' : String(value)

  if (!strVal.trim()) {
    if (!colSchema.nullable) {
      return { message: 'Required' }
    }
    return null
  }

  switch (colSchema.inferred_type) {
    case 'integer':
      if (!/^-?\d+$/.test(strVal.trim())) {
        return { message: 'Must be integer' }
      }
      break
    case 'float':
      if (isNaN(Number(strVal.trim()))) {
        return { message: 'Must be number' }
      }
      break
    case 'boolean':
      if (!['true', 'false', '0', '1', 'yes', 'no'].includes(strVal.trim().toLowerCase())) {
        return { message: 'Must be boolean' }
      }
      break
    case 'date':
      if (!/\d{4}-\d{2}-\d{2}/.test(strVal.trim())) {
        return { message: 'Expected YYYY-MM-DD' }
      }
      break
  }

  return null
}

function EditableCell({
  value,
  colName,
  schema,
  onChange,
}: {
  value: unknown
  colName: string
  schema: Record<string, ColumnSchema>
  onChange: (val: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [localVal, setLocalVal] = useState(value === null || value === undefined ? '' : String(value))
  const error = validateCell(localVal || null, colName, schema)

  const handleBlur = () => {
    setEditing(false)
    if (localVal !== (value === null || value === undefined ? '' : String(value))) {
      onChange(localVal)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      ;(e.target as HTMLInputElement).blur()
    } else if (e.key === 'Escape') {
      setLocalVal(value === null || value === undefined ? '' : String(value))
      setEditing(false)
    }
  }

  // Sync when external value changes
  useEffect(() => {
    if (!editing) {
      setLocalVal(value === null || value === undefined ? '' : String(value))
    }
  }, [value, editing])

  if (!editing) {
    return (
      <div
        className={`px-2 py-1.5 cursor-text min-h-[32px] flex items-center rounded transition-colors hover:bg-accent/10
          ${error ? 'ring-1 ring-destructive/40' : ''}
        `}
        onClick={() => setEditing(true)}
      >
        {localVal ? (
          <span className="text-foreground text-xs truncate max-w-[200px]">{localVal}</span>
        ) : (
          <span className="text-muted-foreground/40 text-xs italic">null</span>
        )}
        {error && (
          <span className="ml-1 shrink-0" title={error.message}>
            <AlertCircle className="h-3 w-3 text-destructive" />
          </span>
        )}
      </div>
    )
  }

  return (
    <div className="relative">
      <Input
        autoFocus
        value={localVal}
        onChange={(e) => setLocalVal(e.target.value)}
        onBlur={handleBlur}
        onKeyDown={handleKeyDown}
        className={`h-8 text-xs ${error ? 'border-destructive focus-visible:ring-destructive/40' : ''}`}
      />
      {error && (
        <span className="absolute -bottom-4 left-0 text-[10px] text-destructive">{error.message}</span>
      )}
    </div>
  )
}

function EditableTable({
  table,
  rows,
  schema,
  onUpdate,
  renamedColumns = new Map(),
}: {
  table: string
  rows: Row[]
  schema: Record<string, ColumnSchema>
  onUpdate: (rows: Row[]) => void
  renamedColumns?: Map<string, string>
}) {
  const columns = rows.length > 0 ? Object.keys(rows[0]) : Object.keys(schema)

  const updateCell = (rowIdx: number, col: string, val: string) => {
    const updated = rows.map((r, i) => (i === rowIdx ? { ...r, [col]: val || null } : r))
    onUpdate(updated)
  }

  const deleteRow = (rowIdx: number) => {
    onUpdate(rows.filter((_, i) => i !== rowIdx))
  }

  const addRow = () => {
    const emptyRow: Row = {}
    for (const col of columns) {
      emptyRow[col] = null
    }
    onUpdate([...rows, emptyRow])
  }

  const errorCount = rows.reduce((total, row) => {
    return total + columns.reduce((colTotal, col) => {
      return colTotal + (validateCell(row[col], col, schema) ? 1 : 0)
    }, 0)
  }, 0)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm flex items-center justify-between">
          <div>
            <span className="text-primary">{table}</span>
            <span className="text-accent ml-2 font-mono text-xs">[{rows.length} rows]</span>
            {errorCount > 0 && (
              <span className="text-destructive ml-2 text-xs">
                {errorCount} issue{errorCount !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          <Button variant="outline" size="sm" onClick={addRow} className="gap-1 h-7 text-xs">
            <Plus className="h-3 w-3" /> Add Row
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto rounded-md border border-border bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/50 border-b border-border">
                <th className="px-2 py-2 text-left text-[10px] font-semibold text-muted-foreground uppercase tracking-wider w-10">
                  #
                </th>
                {columns.map((col) => {
                  const colSchema = schema[col]
                  const displayName = renamedColumns.get(col) || col
                  return (
                    <th key={col} className="px-2 py-2 text-left whitespace-nowrap">
                      <div className="text-xs font-semibold text-primary">{displayName}</div>
                      {colSchema && (
                        <div className="text-[10px] text-muted-foreground font-normal">
                          {colSchema.inferred_type}
                          {!colSchema.nullable && ' · required'}
                        </div>
                      )}
                    </th>
                  )
                })}
                <th className="px-2 py-2 w-10" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIdx) => (
                <tr
                  key={rowIdx}
                  className="border-b border-border/40 last:border-0 hover:bg-accent/5 transition-colors"
                >
                  <td className="px-2 py-1 text-[10px] text-muted-foreground font-mono">
                    {rowIdx + 1}
                  </td>
                  {columns.map((col) => (
                    <td key={col} className="px-1 py-0.5">
                      <EditableCell
                        value={row[col]}
                        colName={col}
                        schema={schema}
                        onChange={(val) => updateCell(rowIdx, col, val)}
                      />
                    </td>
                  ))}
                  <td className="px-2 py-1">
                    <button
                      onClick={() => deleteRow(rowIdx)}
                      className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
                      title="Delete row"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={columns.length + 2} className="px-4 py-8 text-center text-sm text-muted-foreground">
                    No rows. Click "Add Row" to insert data.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

export default function EditPhase() {
  const { state, dispatch } = usePipeline()
  const [tableData, setTableData] = useState<Record<string, Row[]>>({})
  const [schema, setSchema] = useState<Record<string, Record<string, ColumnSchema>>>({})
  const [loaded, setLoaded] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  // Get schema edit state for filtering/renaming
  const droppedTables = state.schemaEditState?.droppedTables ?? new Set()
  const renamedColumns = state.schemaEditState?.renamedColumns ?? new Map()

  useEffect(() => {
    if (!state.sessionId) return
    let cancelled = false
    dispatch({ type: 'SET_LOADING', loading: true })
    fetchTableData(state.sessionId).then((res) => {
      if (cancelled) return
      setTableData(res.tables)
      setSchema(res.schema)
      setLoaded(true)
      dispatch({ type: 'SET_LOADING', loading: false })
    }).catch((e) => {
      if (cancelled) return
      dispatch({ type: 'SET_ERROR', error: e instanceof Error ? e.message : 'Failed to load data' })
    })
    return () => { cancelled = true }
  }, [state.sessionId])

  const updateTable = useCallback((table: string, rows: Row[]) => {
    setTableData((prev) => ({ ...prev, [table]: rows }))
    setDirty(true)
  }, [])

  const totalErrors = Object.entries(tableData).reduce((total, [table, rows]) => {
    const tableSchema = schema[table] ?? {}
    const cols = rows.length > 0 ? Object.keys(rows[0]) : []
    return total + rows.reduce((rowTotal, row) => {
      return rowTotal + cols.reduce((colTotal, col) => {
        return colTotal + (validateCell(row[col], col, tableSchema) ? 1 : 0)
      }, 0)
    }, 0)
  }, 0)

  const handleSaveAndProceed = async () => {
    if (!state.sessionId) return
    setSaving(true)
    try {
      await saveTableData(state.sessionId, tableData)
      dispatch({ type: 'DONE_EDIT' })
    } catch (e: unknown) {
      dispatch({ type: 'SET_ERROR', error: e instanceof Error ? e.message : 'Save failed' })
    } finally {
      setSaving(false)
    }
  }

  const totalRows = Object.values(tableData).reduce((sum, rows) => sum + rows.length, 0)
  // Filter out dropped tables from schema-edit phase
  const tableNames = Object.keys(tableData).filter(t => !droppedTables.has(t))

  if (!loaded) {
    return (
      <div className="space-y-6">
        <PhaseHeader
          phase="edit"
          title="Edit Data"
          description="Loading table data..."
        />
        <div className="flex justify-center py-12">
          <Spinner size="lg" label="Loading table data" />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <PhaseHeader
          phase="edit"
          title="Edit Data"
          description="Review and modify records. Add, edit, or delete rows before configuring the pipeline."
        />
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground hidden sm:inline">
            <span className="text-accent font-mono">{totalRows}</span> rows across{' '}
            <span className="text-accent font-mono">{tableNames.length}</span> tables
            {totalErrors > 0 && (
              <span className="text-destructive ml-2">{totalErrors} issues</span>
            )}
          </span>
        </div>
      </div>

      {tableNames.map((table) => (
        <EditableTable
          key={table}
          table={table}
          rows={tableData[table]}
          schema={schema[table] ?? {}}
          onUpdate={(rows) => updateTable(table, rows)}
          renamedColumns={renamedColumns.get(table) || new Map()}
        />
      ))}

      <div className="flex items-center justify-between">
        <div>
          {dirty && (
            <span className="text-xs text-muted-foreground">Unsaved changes</span>
          )}
        </div>
        <Button
          onClick={handleSaveAndProceed}
          disabled={saving || totalErrors > 0}
        >
          {saving ? 'Saving...' : totalErrors > 0 ? `Fix ${totalErrors} issue${totalErrors !== 1 ? 's' : ''} to proceed` : 'Save & Continue'}
        </Button>
      </div>

      {state.error && (
        <Card className="border-destructive/50">
          <CardContent className="pt-6">
            <p className="text-destructive text-sm">{state.error}</p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
