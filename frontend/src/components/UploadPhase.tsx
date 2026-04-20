import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { usePipeline } from '../store/pipeline'
import { uploadFiles } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/8bit/card'
import { PhaseHeader, Spinner, DataTable } from './ui'

export default function UploadPhase() {
  const { state, dispatch } = usePipeline()

  const onDrop = useCallback(async (accepted: File[]) => {
    if (accepted.length === 0) return
    dispatch({ type: 'SET_LOADING', loading: true })
    try {
      const result = await uploadFiles(accepted)
      dispatch({ type: 'SET_UPLOAD', result })
    } catch (e: unknown) {
      dispatch({ type: 'SET_ERROR', error: e instanceof Error ? e.message : 'Upload failed' })
    }
  }, [dispatch])

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
        className={`relative border-y-6 border-foreground dark:border-ring p-12 text-center cursor-pointer transition-all bg-card group
          ${isDragActive ? 'border-primary bg-primary/5' : 'hover:bg-primary/5'}
        `}
      >
        <div
          className="absolute inset-0 border-x-6 -mx-1.5 border-foreground dark:border-ring pointer-events-none"
          aria-hidden="true"
        />
        <input {...getInputProps()} />
        {state.loading ? (
          <Spinner size="lg" label="Extracting data" />
        ) : (
          <div className="space-y-3 pixel-in">
            <pre className="text-primary/30 text-xs retro leading-tight mx-auto w-fit select-none group-hover:text-primary/50 transition-colors">
{`  ┌─────────┐
  │  ↑ ↑ ↑  │
  │  UPLOAD  │
  └─────────┘`}
            </pre>
            <p className="text-muted-foreground retro text-xs">
              {isDragActive ? '>> Drop files here <<' : 'Drag & drop files here, or click to browse'}
            </p>
            <p className="text-muted-foreground/40 text-[10px] retro">.csv .xlsx .xls .sql</p>
          </div>
        )}
      </div>

      {state.error && (
        <Card>
          <CardContent>
            <p className="text-destructive text-sm retro pixel-in">! ERROR: {state.error}</p>
          </CardContent>
        </Card>
      )}

      {state.uploadResult && (
        <div className="space-y-4 stagger">
          <Card>
            <CardHeader>
              <CardTitle className="text-xs">
                Uploaded Files
                <span className="text-primary/40 ml-2">[{state.uploadResult.files.length}]</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1">
                {state.uploadResult.files.map((f) => (
                  <div key={f.name} className="flex items-center justify-between text-xs retro py-1.5 hover:bg-primary/5 px-1 transition-colors">
                    <span className="text-foreground">
                      <span className="text-primary/40 mr-2">{'>'}</span>
                      {f.name}
                    </span>
                    <span className="text-muted-foreground">{(f.size / 1024).toFixed(1)} KB</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {Object.entries(state.uploadResult.preview).map(([table, rows]) => {
            const cols = rows.length > 0 ? Object.keys(rows[0]) : []
            return (
              <Card key={table}>
                <CardHeader>
                  <CardTitle className="text-xs">
                    Preview: {table}
                    <span className="text-primary/40 ml-2">
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
