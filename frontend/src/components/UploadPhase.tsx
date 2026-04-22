import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { UploadCloud } from 'lucide-react'
import { usePipeline } from '../store/pipeline'
import { uploadFiles } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { PhaseHeader, Spinner, DataTable } from './ui'

export default function UploadPhase() {
  const { state, dispatch } = usePipeline()

  const onDrop = useCallback(async (accepted: File[]) => {
    if (accepted.length === 0) return
    dispatch({ type: 'SET_LOADING', loading: true })
    try {
      const result = await uploadFiles(accepted, state.projectId ?? undefined)
      dispatch({ type: 'SET_UPLOAD', result })
    } catch (e: unknown) {
      dispatch({ type: 'SET_ERROR', error: e instanceof Error ? e.message : 'Upload failed' })
    }
  }, [dispatch, state.projectId])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'text/csv': ['.csv'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
      'application/vnd.ms-excel': ['.xls'],
      'application/sql': ['.sql'],
      'text/plain': ['.sql'],
    },
  })

  return (
    <div className="space-y-6">
      <PhaseHeader
        phase="upload"
        title="Upload Data Files"
        description="Drop CSV, Excel, or SQL dump files to begin the ETL pipeline."
      />

      <div
        {...getRootProps()}
        className={`rounded-lg border-2 border-dashed p-12 text-center cursor-pointer transition-all bg-card
          ${isDragActive ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/60 hover:bg-accent/5'}
        `}
      >
        <input {...getInputProps()} />
        {state.loading ? (
          <Spinner size="lg" label="Extracting data" />
        ) : (
          <div className="space-y-3">
            <UploadCloud className="mx-auto h-12 w-12 text-primary/70" />
            <p className="text-foreground font-medium">
              {isDragActive ? 'Drop files here' : 'Drag & drop files here, or click to browse'}
            </p>
            <p className="text-xs text-muted-foreground">.csv · .xlsx · .xls · .sql</p>
          </div>
        )}
      </div>

      {state.error && (
        <Card className="border-destructive/50">
          <CardContent className="pt-6">
            <p className="text-destructive text-sm">{state.error}</p>
          </CardContent>
        </Card>
      )}

      {state.uploadResult && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">
                Uploaded Files
                <span className="text-accent ml-2 font-mono">[{state.uploadResult.files.length}]</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1">
                {state.uploadResult.files.map((f) => (
                  <div key={f.name} className="flex items-center justify-between text-sm py-1.5 hover:bg-accent/5 px-2 rounded transition-colors">
                    <span className="text-foreground font-mono">{f.name}</span>
                    <span className="text-muted-foreground text-xs">{(f.size / 1024).toFixed(1)} KB</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {state.uploadResult.ddl_schema && Object.keys(state.uploadResult.ddl_schema).length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">
                  DDL Definitions Detected
                  <span className="text-accent ml-2 font-mono text-xs">
                    [{Object.keys(state.uploadResult.ddl_schema).length} tables]
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground mb-2">
                  Schema definitions found. You can apply them in the Configure step.
                </p>
                <div className="space-y-1">
                  {Object.keys(state.uploadResult.ddl_schema).map((table) => (
                    <div key={table} className="text-sm font-mono py-1 px-2">
                      <span className="text-primary/40 mr-2">{'>'}</span>
                      {table}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {Object.entries(state.uploadResult.preview).map(([table, rows]) => {
            const cols = rows.length > 0 ? Object.keys(rows[0]) : []
            return (
              <Card key={table}>
                <CardHeader>
                  <CardTitle className="text-sm">
                    Preview: <span className="text-primary">{table}</span>
                    <span className="text-accent ml-2 font-mono text-xs">
                      [{state.uploadResult!.stats[table]?.row_count ?? 0} rows]
                    </span>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <DataTable columns={cols} rows={rows} maxRows={5} />
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
