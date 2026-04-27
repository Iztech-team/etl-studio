import { useState, useCallback, useEffect } from 'react'
import { usePipeline } from '../store/pipeline'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PhaseHeader, Spinner } from './ui'
import type { ColumnSchema, TableSchema, DDLUploadResponse } from '../types/api'
import { uploadAndParseDDL, saveTemplate } from '../api/client'

export default function SchemaEditPhase() {
  const { state, dispatch } = usePipeline()

  // Get schema from editedSchema (includes DDL updates), falling back to uploadResult, then empty object
  const inferred_schema = state.schemaEditState?.editedSchema ?? state.uploadResult?.inferred_schema ?? {}
  const foreign_keys: any[] = []

  // Local UI state
  const [searchFilter, setSearchFilter] = useState('')
  const [selectedTable, setSelectedTable] = useState<string | null>(null)
  const [expandedTables, setExpandedTables] = useState<Set<string>>(new Set())
  const [ddlModalOpen, setDdlModalOpen] = useState(false)
  const [ddlPreview, setDdlPreview] = useState<DDLUploadResponse | null>(null)
  const [ddlLoading, setDdlLoading] = useState(false)
  const [saveTemplateModalOpen, setSaveTemplateModalOpen] = useState(false)
  const [templateName, setTemplateName] = useState('')
  const [templateLoading, setTemplateLoading] = useState(false)

  // DDL Modal local state
  const [ddlSelectedTable, setDdlSelectedTable] = useState<string | null>(null)
  const [ddlExpandedTables, setDdlExpandedTables] = useState<Set<string>>(new Set())
  const [ddlSearchFilter, setDdlSearchFilter] = useState('')
  const [ddlDroppedTables, setDdlDroppedTables] = useState<Set<string>>(new Set())
  const [ddlDroppedColumns, setDdlDroppedColumns] = useState<Map<string, Set<string>>>(new Map())
  const [ddlRenamedTables, setDdlRenamedTables] = useState<Map<string, string>>(new Map())
  const [ddlRenamedCols, setDdlRenamedCols] = useState<Map<string, Map<string, string>>>(new Map())
  const [ddlSaveTemplateName, setDdlSaveTemplateName] = useState('')
  const [ddlSaveLoading, setDdlSaveLoading] = useState(false)

  // Schema edit state from pipeline
  const schemaEditState = state.schemaEditState
  const droppedTables = schemaEditState?.droppedTables ?? new Set()
  const droppedColumns = schemaEditState?.droppedColumns ?? new Map()
  const renamedTables = schemaEditState?.renamedTables ?? new Map()
  const renamedColumns = schemaEditState?.renamedColumns ?? new Map()
  const nullableOverrides = schemaEditState?.nullableOverrides ?? new Map()

  // Initialize schema edit state if not present
  useEffect(() => {
    if (!schemaEditState) {
      dispatch({
        type: 'SCHEMA_EDIT_INIT',
        payload: { inferred_schema: inferred_schema as any }
      })
    }
  }, [])

  // Compute FK relationships
  const computeRelationships = useCallback(() => {
    const childrenMap = new Map<string, Set<string>>()
    const parentsMap = new Map<string, Set<string>>()

    for (const fk of foreign_keys) {
      // fk.child_table has FK to fk.parent_table
      if (!childrenMap.has(fk.parent_table)) {
        childrenMap.set(fk.parent_table, new Set())
      }
      childrenMap.get(fk.parent_table)!.add(fk.child_table)

      if (!parentsMap.has(fk.child_table)) {
        parentsMap.set(fk.child_table, new Set())
      }
      parentsMap.get(fk.child_table)!.add(fk.parent_table)
    }

    return { childrenMap, parentsMap }
  }, [foreign_keys])

  // Handle actions
  const handleRenameTable = useCallback((tableName: string) => {
    const newName = prompt(`Rename "${tableName}" to:`)
    if (newName) {
      const trimmedName = newName.trim()
      if (!trimmedName) {
        alert('Table name cannot be empty')
        return
      }
      if (trimmedName === tableName) {
        alert('New name is the same as current name')
        return
      }
      // Check if new name already exists
      const allTableNames = new Set(Object.keys(inferred_schema))
      if (allTableNames.has(trimmedName)) {
        alert(`Table "${trimmedName}" already exists`)
        return
      }
      dispatch({
        type: 'SCHEMA_EDIT_RENAME_TABLE',
        payload: { tableName, newName: trimmedName }
      })
    }
  }, [dispatch, inferred_schema])

  const handleDropTable = useCallback((tableName: string) => {
    dispatch({
      type: 'SCHEMA_EDIT_DROP_TABLE',
      payload: { tableName }
    })
  }, [dispatch])

  const handleRenameColumn = useCallback((tableName: string, colName: string) => {
    const newName = prompt(`Rename "${colName}" to:`)
    if (newName) {
      const trimmedName = newName.trim()
      if (!trimmedName) {
        alert('Column name cannot be empty')
        return
      }
      if (trimmedName === colName) {
        alert('New name is the same as current name')
        return
      }
      // Check if new name already exists in the table
      const tableSchema = inferred_schema[tableName] ?? {}
      if (trimmedName in tableSchema) {
        alert(`Column "${trimmedName}" already exists in this table`)
        return
      }
      dispatch({
        type: 'SCHEMA_EDIT_RENAME_COLUMN',
        payload: { tableName, colName, newName: trimmedName }
      })
    }
  }, [dispatch, inferred_schema])

  const handleDropColumn = useCallback((tableName: string, colName: string) => {
    dispatch({
      type: 'SCHEMA_EDIT_DROP_COLUMN',
      payload: { tableName, colName }
    })
  }, [dispatch])

  const handleToggleNullable = useCallback((tableName: string, colName: string, nullable: boolean) => {
    dispatch({
      type: 'SCHEMA_EDIT_TOGGLE_NULLABLE',
      payload: { tableName, colName, nullable: !nullable }
    })
  }, [dispatch])

  const handleReorderColumn = useCallback((tableName: string, colName: string, direction: 'up' | 'down') => {
    dispatch({
      type: 'SCHEMA_EDIT_REORDER_COLUMN',
      payload: { tableName, colName, direction }
    })
  }, [dispatch])

  const handleSkip = useCallback(() => {
    dispatch({ type: 'SCHEMA_EDIT_SKIP' })
  }, [dispatch])

  const handleApply = useCallback(() => {
    // Warn if all tables are dropped
    const allTables = Object.keys(inferred_schema)
    const remainingTables = allTables.filter(t => !droppedTables.has(t))
    if (remainingTables.length === 0) {
      const confirmed = confirm('All tables are dropped! Are you sure you want to continue?')
      if (!confirmed) return
    }
    dispatch({ type: 'SCHEMA_EDIT_APPLY' })
  }, [dispatch, inferred_schema, droppedTables])

  const handleDDLUpload = useCallback(async (file: File) => {
    if (!file.name.endsWith('.sql')) {
      alert('Please upload a .sql file')
      return
    }

    setDdlLoading(true)
    try {
      const result = await uploadAndParseDDL(state.sessionId!, file)
      if (!result || !result.ddl_schema) {
        alert('Invalid DDL response from server')
        return
      }
      const matchingCount = result.matching_tables?.length ?? 0
      if (matchingCount === 0) {
        alert('No matching tables found in DDL')
        return
      }
      setDdlPreview(result)
      setDdlModalOpen(true)
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error)
      alert('DDL parsing failed:\n' + errorMsg)
    } finally {
      setDdlLoading(false)
    }
  }, [state.sessionId])


  const handleSaveTemplate = useCallback(async () => {
    const trimmedName = templateName.trim()
    if (!trimmedName) {
      alert('Template name required')
      return
    }

    if (trimmedName.length > 100) {
      alert('Template name is too long (max 100 characters)')
      return
    }

    if (!state.projectId) {
      alert('No project ID available')
      return
    }

    if (!state.schemaEditState?.modified) {
      alert('No changes to save')
      return
    }

    setTemplateLoading(true)
    try {
      const ddlContent = JSON.stringify(state.schemaEditState?.editedSchema, null, 2)
      await saveTemplate(state.projectId, trimmedName, ddlContent)
      alert('Template saved successfully!')
      setSaveTemplateModalOpen(false)
      setTemplateName('')
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error)
      alert('Failed to save template:\n' + errorMsg)
    } finally {
      setTemplateLoading(false)
    }
  }, [templateName, state.projectId, state.schemaEditState?.editedSchema, state.schemaEditState?.modified])

  // DDL Modal handlers
  const closeDdlModal = useCallback(() => {
    setDdlModalOpen(false)
    setDdlPreview(null)
    setDdlSelectedTable(null)
    setDdlExpandedTables(new Set())
    setDdlSearchFilter('')
    setDdlDroppedTables(new Set())
    setDdlDroppedColumns(new Map())
    setDdlRenamedTables(new Map())
    setDdlRenamedCols(new Map())
    setDdlSaveTemplateName('')
  }, [])

  const handleDdlRenameTable = useCallback((tableName: string) => {
    const newName = prompt(`Rename "${tableName}" to:`)
    if (newName) {
      const trimmedName = newName.trim()
      if (!trimmedName) {
        alert('Table name cannot be empty')
        return
      }
      if (trimmedName === tableName) {
        alert('New name is the same as current name')
        return
      }
      const allTableNames = ddlPreview?.ddl_schema ? new Set(Object.keys(ddlPreview.ddl_schema)) : new Set()
      if (allTableNames.has(trimmedName) && !ddlRenamedTables.has(trimmedName)) {
        alert(`Table "${trimmedName}" already exists`)
        return
      }
      setDdlRenamedTables(new Map(ddlRenamedTables).set(tableName, trimmedName))
    }
  }, [ddlPreview, ddlRenamedTables])

  const handleDdlDropTable = useCallback((tableName: string) => {
    setDdlDroppedTables(new Set(
      ddlDroppedTables.has(tableName)
        ? [...ddlDroppedTables].filter(t => t !== tableName)
        : [...ddlDroppedTables, tableName]
    ))
  }, [ddlDroppedTables])

  const handleDdlRenameColumn = useCallback((tableName: string, colName: string) => {
    const newName = prompt(`Rename "${colName}" to:`)
    if (newName) {
      const trimmedName = newName.trim()
      if (!trimmedName) {
        alert('Column name cannot be empty')
        return
      }
      if (trimmedName === colName) {
        alert('New name is the same as current name')
        return
      }
      const tableSchema = ddlPreview?.ddl_schema[tableName] ?? {}
      if (trimmedName in tableSchema && !ddlRenamedCols.get(tableName)?.has(trimmedName)) {
        alert(`Column "${trimmedName}" already exists in this table`)
        return
      }
      const newRenamedCols = new Map(ddlRenamedCols)
      const tableRenames = newRenamedCols.get(tableName) || new Map()
      tableRenames.set(colName, trimmedName)
      newRenamedCols.set(tableName, tableRenames)
      setDdlRenamedCols(newRenamedCols)
    }
  }, [ddlPreview, ddlRenamedCols])

  const handleDdlDropColumn = useCallback((tableName: string, colName: string) => {
    const droppedCols = new Map(ddlDroppedColumns)
    const tableDropped = droppedCols.get(tableName) || new Set()
    const newTableDropped = new Set(tableDropped)
    if (newTableDropped.has(colName)) {
      newTableDropped.delete(colName)
    } else {
      newTableDropped.add(colName)
    }
    droppedCols.set(tableName, newTableDropped)
    setDdlDroppedColumns(droppedCols)
  }, [ddlDroppedColumns])

  const buildCustomizedDDL = useCallback(() => {
    if (!ddlPreview) return {}
    const result: Record<string, any> = {}
    for (const [table, cols] of Object.entries(ddlPreview.ddl_schema)) {
      if (ddlDroppedTables.has(table)) continue
      const finalTableName = ddlRenamedTables.get(table) ?? table
      const droppedCols = ddlDroppedColumns.get(table) ?? new Set()
      const renamedCols = ddlRenamedCols.get(table) ?? new Map()
      const filteredCols: Record<string, any> = {}
      for (const [col, info] of Object.entries(cols)) {
        if (droppedCols.has(col)) continue
        const finalColName = renamedCols.get(col) ?? col
        filteredCols[finalColName] = info
      }
      result[finalTableName] = filteredCols
    }
    return result
  }, [ddlPreview, ddlDroppedTables, ddlRenamedTables, ddlDroppedColumns, ddlRenamedCols])

  const handleDdlApply = useCallback(() => {
    if (ddlPreview) {
      const customized = buildCustomizedDDL()
      dispatch({
        type: 'SCHEMA_EDIT_APPLY_DDL',
        payload: {
          ...ddlPreview,
          ddl_schema: customized
        }
      })
      closeDdlModal()
    }
  }, [ddlPreview, buildCustomizedDDL, dispatch, closeDdlModal])

  const handleDdlSaveTemplate = useCallback(async () => {
    const trimmedName = ddlSaveTemplateName.trim()
    if (!trimmedName) {
      alert('Template name required')
      return
    }
    if (trimmedName.length > 100) {
      alert('Template name is too long (max 100 characters)')
      return
    }
    if (!state.projectId) {
      alert('No project ID available')
      return
    }

    setDdlSaveLoading(true)
    try {
      const customized = buildCustomizedDDL()
      const ddlContent = JSON.stringify(customized, null, 2)
      await saveTemplate(state.projectId, trimmedName, ddlContent)
      alert('Template saved successfully!')
      setDdlSaveTemplateName('')
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error)
      alert('Failed to save template:\n' + errorMsg)
    } finally {
      setDdlSaveLoading(false)
    }
  }, [ddlSaveTemplateName, state.projectId, buildCustomizedDDL])

  // Keyboard shortcuts for DDL modal
  useEffect(() => {
    if (!ddlModalOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      const key = e.key.toLowerCase()

      // Escape closes modal
      if (key === 'escape') {
        e.preventDefault()
        e.stopPropagation()
        closeDdlModal()
        return
      }

      const ddlTables = ddlPreview ? Object.keys(ddlPreview.ddl_schema).filter(t =>
        t.toLowerCase().includes(ddlSearchFilter.toLowerCase())
      ) : []
      const currentIdx = ddlTables.indexOf(ddlSelectedTable || '')

      // Navigate tables with arrow keys
      if (key === 'arrowup' || key === 'arrowdown') {
        e.preventDefault()
        if (key === 'arrowup' && currentIdx > 0) {
          setDdlSelectedTable(ddlTables[currentIdx - 1])
        } else if (key === 'arrowdown' && currentIdx < ddlTables.length - 1) {
          setDdlSelectedTable(ddlTables[currentIdx + 1])
        }
      }

      // Rename with R
      if (key === 'r' && ddlSelectedTable) {
        e.preventDefault()
        handleDdlRenameTable(ddlSelectedTable)
      }

      // Drop with D
      if (key === 'd' && ddlSelectedTable) {
        e.preventDefault()
        handleDdlDropTable(ddlSelectedTable)
      }

      // Expand with Space
      if (key === ' ' && ddlSelectedTable) {
        e.preventDefault()
        setDdlExpandedTables(prev => {
          const next = new Set(prev)
          if (next.has(ddlSelectedTable)) next.delete(ddlSelectedTable)
          else next.add(ddlSelectedTable)
          return next
        })
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [ddlModalOpen, ddlSelectedTable, ddlSearchFilter, ddlPreview, closeDdlModal, handleDdlRenameTable, handleDdlDropTable])

  // Keyboard shortcuts for main schema editor
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Only when phase is active and DDL modal not open
      if (state.phase !== 'schema-edit' || ddlModalOpen) return

      const key = e.key.toLowerCase()

      // Navigate tables with arrow keys
      if (key === 'arrowup' || key === 'arrowdown') {
        e.preventDefault()
        const tables = Object.keys(inferred_schema)
        const filtered = tables.filter(t => t.toLowerCase().includes(searchFilter.toLowerCase()))
        const currentIdx = filtered.indexOf(selectedTable || '')

        if (key === 'arrowup' && currentIdx > 0) {
          setSelectedTable(filtered[currentIdx - 1])
        } else if (key === 'arrowdown' && currentIdx < filtered.length - 1) {
          setSelectedTable(filtered[currentIdx + 1])
        }
      }

      // Rename with R
      if (key === 'r' && selectedTable) {
        e.preventDefault()
        handleRenameTable(selectedTable)
      }

      // Drop with D
      if (key === 'd' && selectedTable) {
        e.preventDefault()
        handleDropTable(selectedTable)
      }

      // Expand with Space
      if (key === ' ' && selectedTable) {
        e.preventDefault()
        setExpandedTables(prev => {
          const next = new Set(prev)
          if (next.has(selectedTable)) next.delete(selectedTable)
          else next.add(selectedTable)
          return next
        })
      }

      // Skip with Esc
      if (key === 'escape') {
        e.preventDefault()
        dispatch({ type: 'SCHEMA_EDIT_SKIP' })
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedTable, searchFilter, inferred_schema, state.phase, dispatch, ddlModalOpen, handleRenameTable, handleDropTable])

  // Filter tables based on search
  const filteredTables = Object.keys(inferred_schema).filter(tableName =>
    tableName.toLowerCase().includes(searchFilter.toLowerCase())
  )

  const { childrenMap, parentsMap } = computeRelationships()

  return (
    <div className="space-y-6">
      <PhaseHeader
        title="Schema Editor"
        description="Rename tables/columns, drop tables, reorder columns (optional step)"
      />
      <div className="text-xs bg-muted/40 border rounded p-2 text-muted-foreground flex flex-wrap gap-x-4 gap-y-1">
        <span className="font-semibold text-foreground">Shortcuts:</span>
        <span><span className="font-mono bg-muted px-1 rounded">↑↓</span> navigate</span>
        <span><span className="font-mono bg-muted px-1 rounded">R</span> rename</span>
        <span><span className="font-mono bg-muted px-1 rounded">D</span> drop/restore</span>
        <span><span className="font-mono bg-muted px-1 rounded">Space</span> expand columns</span>
        <span><span className="font-mono bg-muted px-1 rounded">Esc</span> skip phase</span>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Tables ({filteredTables.length})</CardTitle>
          <div className="flex gap-2">
            <Input
              placeholder="Search tables..."
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              className="w-64"
            />
            <Button variant="outline" size="sm">↻</Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => document.getElementById('ddl-input')?.click()}
              disabled={ddlLoading}
            >
              {ddlLoading ? '...' : '[DDL↑]'}
            </Button>
            <input
              id="ddl-input"
              type="file"
              accept=".sql"
              style={{ display: 'none' }}
              onChange={(e) => e.target.files && handleDDLUpload(e.target.files[0])}
            />
          </div>
        </CardHeader>
        <CardContent>
          {filteredTables.length === 0 ? (
            <div className="text-gray-500 py-8 text-center">
              No tables match your search.
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {filteredTables.map(tableName => {
                const isExpanded = expandedTables.has(tableName)
                const isDropped = droppedTables.has(tableName)
                const children = childrenMap.get(tableName) || new Set()
                const parents = parentsMap.get(tableName) || new Set()
                const colCount = Object.keys(inferred_schema[tableName] ?? {}).length

                return (
                  <div
                    key={tableName}
                    className={`border rounded-lg p-3 cursor-pointer transition ${
                      selectedTable === tableName ? 'bg-blue-50 border-blue-500' : 'hover:bg-gray-50'
                    } ${isDropped ? 'opacity-50 line-through' : ''}`}
                    onClick={() => {
                      setSelectedTable(tableName)
                      setExpandedTables(prev => {
                        const next = new Set(prev)
                        if (next.has(tableName)) next.delete(tableName)
                        else next.add(tableName)
                        return next
                      })
                    }}
                  >
                    <div className="font-semibold text-sm">{tableName}</div>
                    <div className="text-xs text-gray-600">
                      {colCount} columns
                    </div>
                    <div
                      className="text-xs text-gray-500 mt-1 flex gap-2"
                      title={`Children: ${Array.from(children).join(', ') || 'none'}\nParents: ${Array.from(parents).join(', ') || 'none'}`}
                    >
                      {children.size > 0 && <span>↓ {children.size}</span>}
                      {parents.size > 0 && <span>↑ {parents.size}</span>}
                    </div>
                    <div className="flex gap-1 mt-2">
                      <button
                        className="text-xs px-2 py-1 border rounded hover:bg-gray-100"
                        onClick={(e) => {
                          e.stopPropagation()
                          handleRenameTable(tableName)
                        }}
                      >
                        [R]
                      </button>
                      <button
                        className="text-xs px-2 py-1 border rounded hover:bg-gray-100"
                        onClick={(e) => {
                          e.stopPropagation()
                          handleDropTable(tableName)
                        }}
                      >
                        [D]
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Column editor for expanded table */}
      {selectedTable && expandedTables.has(selectedTable) && (
        <Card className="border-blue-500 mt-4">
          <CardHeader>
            <CardTitle className="text-lg">{selectedTable} - Columns</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {Object.entries(inferred_schema[selectedTable] ?? {}).map(([colName, colInfo]) => {
              const isDropped = droppedColumns.get(selectedTable)?.has(colName)
              const isNullable = nullableOverrides.get(selectedTable)?.has(colName) ?? (colInfo as ColumnSchema).nullable

              return (
                <div
                  key={colName}
                  className={`flex items-center gap-2 p-2 border rounded ${
                    isDropped ? 'opacity-50 line-through' : ''
                  }`}
                >
                  <div className="flex gap-1">
                    <button
                      className="text-xs px-2 py-1 border rounded hover:bg-gray-100"
                      onClick={() => handleReorderColumn(selectedTable, colName, 'up')}
                    >
                      [↑]
                    </button>
                    <button
                      className="text-xs px-2 py-1 border rounded hover:bg-gray-100"
                      onClick={() => handleReorderColumn(selectedTable, colName, 'down')}
                    >
                      [↓]
                    </button>
                  </div>
                  <div className="flex-1">
                    <div className="font-semibold text-sm">{colName}</div>
                    <div className="text-xs text-gray-600">
                      {(colInfo as ColumnSchema).inferred_type}
                      {isNullable ? ', nullable' : ', NOT NULL'}
                    </div>
                  </div>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={isNullable}
                      onChange={() => handleToggleNullable(selectedTable, colName, isNullable)}
                    />
                    Nullable
                  </label>
                  <button
                    className="text-xs px-2 py-1 border rounded hover:bg-gray-100"
                    onClick={() => handleRenameColumn(selectedTable, colName)}
                  >
                    [R]
                  </button>
                  <button
                    className="text-xs px-2 py-1 border rounded hover:bg-gray-100"
                    onClick={() => handleDropColumn(selectedTable, colName)}
                  >
                    [D]
                  </button>
                </div>
              )
            })}
          </CardContent>
        </Card>
      )}

      {/* DDL Preview Modal */}
      {ddlModalOpen && ddlPreview && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <Card className="w-full max-w-4xl max-h-[80vh] flex flex-col">
            <CardHeader className="flex-shrink-0 space-y-3">
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-2">
                  <CardTitle>DDL Preview</CardTitle>
                  <span className="text-sm text-gray-500">
                    {ddlPreview.matching_tables.length} matching, {Object.keys(ddlPreview.ddl_schema).length} total
                  </span>
                </div>
                <Input
                  placeholder="Search tables..."
                  value={ddlSearchFilter}
                  onChange={(e) => setDdlSearchFilter(e.target.value)}
                  className="w-48"
                />
              </div>
              <div className="text-xs bg-blue-50 border border-blue-200 rounded p-2 text-blue-900">
                <span className="font-semibold">Keyboard shortcuts:</span> <span className="font-mono ml-2">↑↓</span> navigate · <span className="font-mono">R</span> rename · <span className="font-mono">D</span> drop · <span className="font-mono">Space</span> expand · <span className="font-mono">Esc</span> close
              </div>
            </CardHeader>

            <CardContent className="flex-1 overflow-hidden flex gap-4 p-4">
              {/* Left panel - Table list */}
              <div className="flex-1 overflow-auto border rounded">
                <div className="grid grid-cols-2 gap-2 p-4">
                  {(ddlPreview ? Object.keys(ddlPreview.ddl_schema).filter(t =>
                    t.toLowerCase().includes(ddlSearchFilter.toLowerCase())
                  ) : []).map(tableName => {
                    const isMatching = ddlPreview.matching_tables.includes(tableName)
                    const isSelected = ddlSelectedTable === tableName
                    const isDropped = ddlDroppedTables.has(tableName)
                    const colCount = Object.keys(ddlPreview.ddl_schema[tableName] ?? {}).length
                    const isExpanded = ddlExpandedTables.has(tableName)

                    return (
                      <div
                        key={tableName}
                        className={`border rounded-lg p-3 cursor-pointer transition ${
                          isSelected ? 'bg-blue-50 border-blue-500' : 'hover:bg-gray-50'
                        } ${isDropped ? 'opacity-50 line-through' : ''} ${!isMatching ? 'bg-gray-100' : ''}`}
                        onClick={() => {
                          setDdlSelectedTable(tableName)
                          setDdlExpandedTables(prev => {
                            const next = new Set(prev)
                            if (next.has(tableName)) next.delete(tableName)
                            else next.add(tableName)
                            return next
                          })
                        }}
                      >
                        <div className="flex items-center gap-2">
                          {isMatching && <span className="text-green-600 text-xs">●</span>}
                          <div className="font-semibold text-sm flex-1">{tableName}</div>
                          {isExpanded && <span className="text-xs">▼</span>}
                        </div>
                        <div className="text-xs text-gray-600">{colCount} columns</div>
                        <div className="flex gap-1 mt-2">
                          <button
                            className="text-xs px-2 py-1 border rounded hover:bg-gray-100"
                            onClick={(e) => {
                              e.stopPropagation()
                              handleDdlRenameTable(tableName)
                            }}
                          >
                            [R]
                          </button>
                          <button
                            className="text-xs px-2 py-1 border rounded hover:bg-gray-100"
                            onClick={(e) => {
                              e.stopPropagation()
                              handleDdlDropTable(tableName)
                            }}
                          >
                            [D]
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Right panel - Column editor */}
              {ddlSelectedTable && ddlExpandedTables.has(ddlSelectedTable) && (
                <div className="flex-1 overflow-auto border rounded p-4 bg-gray-50">
                  <div className="space-y-2">
                    <div className="font-semibold text-sm pb-2 border-b">{ddlSelectedTable} - Columns</div>
                    {Object.entries(ddlPreview.ddl_schema[ddlSelectedTable] ?? {}).map(([colName, colInfo]: any) => {
                      const isDropped = ddlDroppedColumns.get(ddlSelectedTable)?.has(colName)
                      const finalColName = ddlRenamedCols.get(ddlSelectedTable)?.get(colName) ?? colName
                      return (
                        <div
                          key={colName}
                          className={`flex items-center gap-2 p-2 border rounded text-sm ${
                            isDropped ? 'opacity-50 line-through' : ''
                          }`}
                        >
                          <div className="flex-1">
                            <div className="font-semibold text-xs">{finalColName}</div>
                            <div className="text-xs text-gray-600">{colInfo.inferred_type || colInfo.data_type}</div>
                          </div>
                          <div className="flex gap-1">
                            <button
                              className="text-xs px-2 py-1 border rounded hover:bg-gray-100"
                              onClick={() => handleDdlRenameColumn(ddlSelectedTable, colName)}
                            >
                              [R]
                            </button>
                            <button
                              className="text-xs px-2 py-1 border rounded hover:bg-gray-100"
                              onClick={() => handleDdlDropColumn(ddlSelectedTable, colName)}
                            >
                              [D]
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </CardContent>

            {/* Footer */}
            <div className="flex-shrink-0 border-t p-4 space-y-2">
              <div className="flex gap-1 items-center">
                <Input
                  placeholder="Template name (optional)"
                  value={ddlSaveTemplateName}
                  onChange={(e) => setDdlSaveTemplateName(e.target.value)}
                  className="flex-1"
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleDdlSaveTemplate}
                  disabled={ddlSaveLoading || !ddlSaveTemplateName.trim()}
                >
                  {ddlSaveLoading ? '...' : 'Save'}
                </Button>
              </div>
              <div className="flex gap-2 justify-end">
                <Button variant="default" onClick={handleDdlApply}>
                  Apply
                </Button>
                <Button variant="outline" onClick={closeDdlModal}>
                  Cancel
                </Button>
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* Save Template Modal */}
      {saveTemplateModalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <Card className="w-96">
            <CardHeader>
              <CardTitle>Save as Template</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Input
                placeholder="Template name (e.g., 'Baraka v18 Standard')"
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
              />
              <div className="flex gap-2">
                <Button
                  variant="default"
                  onClick={handleSaveTemplate}
                  disabled={templateLoading || !templateName.trim()}
                >
                  {templateLoading ? 'Saving...' : 'Save'}
                </Button>
                <Button variant="outline" onClick={() => {
                  setSaveTemplateModalOpen(false)
                  setTemplateName('')
                }}>
                  Cancel
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-2">
        <Button
          onClick={() => setSaveTemplateModalOpen(true)}
          variant="outline"
          disabled={!state.schemaEditState?.modified}
        >
          Save as Template
        </Button>
        <Button onClick={handleApply} variant="default">
          Apply Changes
        </Button>
        <Button onClick={handleSkip} variant="outline">
          Skip & Continue
        </Button>
      </div>
    </div>
  )
}
