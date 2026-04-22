import { useState, useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { Database, HardDrive, Lock, ArrowRight } from 'lucide-react'
import { usePipeline } from '../store/pipeline'
import { preExtract, preExtractSelect } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Progress } from '@/components/ui/progress'
import { PhaseHeader, Spinner, DataTable } from './ui'

const DB_FORMATS = [
  { type: 'SQLite', extensions: '.sqlite, .sqlite3, .db' },
  { type: 'Firebird / Interbase', extensions: '.fdb, .gdb, .ib' },
  { type: 'MS Access', extensions: '.mdb, .accdb' },
  { type: 'dBase', extensions: '.dbf' },
]

const ACCEPT_MAP: Record<string, string[]> = {
  'application/octet-stream': [
    '.sqlite', '.sqlite3', '.db',
    '.fdb', '.gdb', '.ib',
    '.mdb', '.accdb',
    '.dbf',
  ],
}

export default function PreExtractPhase() {
  const { state, dispatch } = usePipeline()
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [selectedTables, setSelectedTables] = useState<Set<string>>(new Set())

  const extracted = state.preExtractResult

  const onDrop = useCallback((accepted: File[]) => {
    if (accepted.length > 0) {
      setSelectedFile(accepted[0])
      setUploadProgress(null)
    }
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPT_MAP,
    multiple: false,
  })

  const handleUpload = async () => {
    if (!selectedFile) return
    dispatch({ type: 'SET_LOADING', loading: true })
    setUploadProgress(0)
    try {
      const result = await preExtract(
        selectedFile,
        password || undefined,
        (percent) => setUploadProgress(percent),
        state.projectId ?? undefined,
      )
      // Select all tables by default
      setSelectedTables(new Set(result.tables_extracted))
      dispatch({ type: 'SET_PRE_EXTRACT', result })
    } catch (e: unknown) {
      dispatch({ type: 'SET_ERROR', error: e instanceof Error ? e.message : 'Upload failed' })
      setUploadProgress(null)
    }
  }

  const handleSkip = () => {
    dispatch({ type: 'SKIP_PRE_EXTRACT' })
  }

  const toggleTable = (table: string) => {
    setSelectedTables((prev) => {
      const next = new Set(prev)
      if (next.has(table)) next.delete(table)
      else next.add(table)
      return next
    })
  }

  const toggleAll = () => {
    if (!extracted) return
    if (selectedTables.size === extracted.tables_extracted.length) {
      setSelectedTables(new Set())
    } else {
      setSelectedTables(new Set(extracted.tables_extracted))
    }
  }

  const handleProceed = async () => {
    if (!extracted || selectedTables.size === 0) return
    dispatch({ type: 'SET_LOADING', loading: true })
    try {
      await preExtractSelect(extracted.session_id, [...selectedTables])
      dispatch({ type: 'CONFIRM_PRE_EXTRACT', selectedTables: [...selectedTables] })
    } catch (e: unknown) {
      dispatch({ type: 'SET_ERROR', error: e instanceof Error ? e.message : 'Selection failed' })
    }
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
  }

  const getDbTypeLabel = (filename: string) => {
    const ext = filename.slice(filename.lastIndexOf('.')).toLowerCase()
    for (const fmt of DB_FORMATS) {
      if (fmt.extensions.split(', ').some((e) => e.trim() === ext)) {
        return fmt.type
      }
    }
    return 'Unknown'
  }

  // Before extraction: show upload UI
  if (!extracted) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <PhaseHeader
            phase="pre-extract"
            title="Database Import"
            description="Upload a database file to extract tables, or skip to upload flat files directly."
          />
          <Button variant="outline" size="sm" onClick={handleSkip} className="gap-1.5">
            Skip <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </div>

        <div
          {...getRootProps()}
          className={`rounded-lg border-2 border-dashed p-12 text-center cursor-pointer transition-all bg-card
            ${isDragActive ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/60 hover:bg-accent/5'}
          `}
        >
          <input {...getInputProps()} />
          {state.loading ? (
            <Spinner size="lg" label="Extracting tables from database" />
          ) : (
            <div className="space-y-3">
              <Database className="mx-auto h-12 w-12 text-primary/70" />
              <p className="text-foreground font-medium">
                {isDragActive ? 'Drop database file here' : 'Drag & drop a database file, or click to browse'}
              </p>
              <p className="text-xs text-muted-foreground">
                {DB_FORMATS.map((f) => f.extensions).join(' · ')}
              </p>
            </div>
          )}
        </div>

        {uploadProgress !== null && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>Uploading...</span>
              <span className="font-mono text-accent">{uploadProgress}%</span>
            </div>
            <Progress value={uploadProgress} className="h-2" />
          </div>
        )}

        {selectedFile && !state.loading && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Selected File</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center gap-3 p-3 bg-muted/30 rounded-md">
                <HardDrive className="h-8 w-8 text-primary/60 shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-mono text-foreground truncate">{selectedFile.name}</p>
                  <div className="flex items-center gap-3 mt-1">
                    <span className="text-xs text-muted-foreground">{formatSize(selectedFile.size)}</span>
                    <span className="text-xs px-1.5 py-0.5 bg-primary/10 text-primary rounded font-mono">
                      {getDbTypeLabel(selectedFile.name)}
                    </span>
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <label className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Lock className="h-3.5 w-3.5" />
                  Database Password
                  <span className="text-xs">(optional)</span>
                </label>
                <div className="flex gap-2">
                  <Input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Enter password if database is encrypted"
                    className="flex-1"
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowPassword(!showPassword)}
                    className="text-xs px-3"
                  >
                    {showPassword ? 'Hide' : 'Show'}
                  </Button>
                </div>
              </div>

              <Button onClick={handleUpload} className="w-full">
                Upload & Extract
              </Button>
            </CardContent>
          </Card>
        )}

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

  // After extraction: show table previews with selection checkboxes
  const allSelected = selectedTables.size === extracted.tables_extracted.length
  const noneSelected = selectedTables.size === 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <PhaseHeader
          phase="pre-extract"
          title="Select Tables"
          description={`${extracted.tables_extracted.length} tables extracted from ${extracted.file.name}. Select which to include in the pipeline.`}
        />
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground hidden sm:inline">
            <span className="text-accent font-mono">{selectedTables.size}</span>/{extracted.tables_extracted.length} selected
          </span>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center justify-between">
            <div className="flex items-center gap-2">
              <HardDrive className="h-4 w-4 text-primary/60" />
              <span>{extracted.file.name}</span>
              <span className="text-accent font-mono text-xs">[{extracted.file.db_type}]</span>
            </div>
            <Button variant="ghost" size="sm" onClick={toggleAll} className="text-xs h-7">
              {allSelected ? 'Deselect All' : 'Select All'}
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-1">
            {extracted.tables_extracted.map((table) => {
              const rowCount = extracted.stats[table]?.row_count ?? 0
              const colCount = extracted.preview[table]?.[0]
                ? Object.keys(extracted.preview[table][0]).length
                : 0
              return (
                <div
                  key={table}
                  className={`flex items-center gap-3 px-3 py-2 rounded-md transition-colors cursor-pointer
                    ${selectedTables.has(table) ? 'bg-primary/5' : 'hover:bg-accent/5 opacity-50'}
                  `}
                  onClick={() => toggleTable(table)}
                >
                  <Checkbox
                    checked={selectedTables.has(table)}
                    onCheckedChange={() => toggleTable(table)}
                  />
                  <span className="font-mono text-sm text-foreground flex-1">{table}</span>
                  <span className="text-xs text-muted-foreground">
                    {rowCount.toLocaleString()} rows · {colCount} cols
                  </span>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {extracted.tables_extracted.map((table) => {
        if (!selectedTables.has(table)) return null
        const rows = extracted.preview[table] ?? []
        const cols = rows.length > 0 ? Object.keys(rows[0]) : []
        const rowCount = extracted.stats[table]?.row_count ?? 0

        return (
          <Card key={table}>
            <CardHeader>
              <CardTitle className="text-sm">
                Preview: <span className="text-primary">{table}</span>
                <span className="text-accent ml-2 font-mono text-xs">
                  [{rowCount.toLocaleString()} rows]
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {cols.length > 0 ? (
                <DataTable columns={cols} rows={rows} maxRows={5} />
              ) : (
                <p className="text-xs text-muted-foreground">No data in this table.</p>
              )}
            </CardContent>
          </Card>
        )
      })}

      <div className="flex justify-end gap-3">
        <Button onClick={handleProceed} disabled={noneSelected || state.loading}>
          {state.loading ? 'Processing...' : `Proceed with ${selectedTables.size} Table${selectedTables.size !== 1 ? 's' : ''}`}
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
