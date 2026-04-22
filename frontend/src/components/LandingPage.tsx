import { useState } from 'react'
import { FolderPlus, FolderOpen, Zap, Pencil, Trash2, Check, X } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Spinner } from '@/components/ui'
import { usePipeline, type Phase } from '../store/pipeline'
import { createProject, listProjects, renameProject, deleteProject, resumeProject } from '../api/projects'
import type { Project } from '../types/project'
import type { ValidateResponse, TransformResponse, LoadResponse } from '../types/api'

type Selection = 'create' | 'open' | null

export default function LandingPage() {
  const { dispatch } = usePipeline()
  const [selection, setSelection] = useState<Selection>(null)

  // Create project state
  const [createUsername, setCreateUsername] = useState('')
  const [createName, setCreateName] = useState('')
  const [createLoading, setCreateLoading] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  // Open project state
  const [openUsername, setOpenUsername] = useState('')
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [openLoading, setOpenLoading] = useState(false)
  const [openError, setOpenError] = useState<string | null>(null)
  const [resumingId, setResumingId] = useState<string | null>(null)

  // Rename state
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')

  function handleSelect(sel: Selection) {
    setSelection(selection === sel ? null : sel)
  }

  async function handleCreate() {
    if (!createUsername.trim() || !createName.trim()) return
    setCreateLoading(true)
    setCreateError(null)
    try {
      const project = await createProject(createName.trim(), createUsername.trim())
      dispatch({ type: 'SET_PROJECT', projectId: project.id, projectName: project.name })
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'Failed to create project')
    } finally {
      setCreateLoading(false)
    }
  }

  async function handleLoadProjects() {
    if (!openUsername.trim()) return
    setOpenLoading(true)
    setOpenError(null)
    try {
      const list = await listProjects(openUsername.trim())
      setProjects(list)
    } catch (err) {
      setOpenError(err instanceof Error ? err.message : 'Failed to load projects')
    } finally {
      setOpenLoading(false)
    }
  }

  async function handleResume(project: Project) {
    setResumingId(project.id)
    setOpenError(null)
    try {
      const res = await resumeProject(project.id)
      dispatch({
        type: 'RESTORE_PROJECT',
        projectId: project.id,
        projectName: project.name,
        sessionId: res.session_id,
        phase: res.phase as Phase,
        uploadResult: res.files.length > 0 ? {
          session_id: res.session_id,
          files: res.files,
          preview: res.preview,
          inferred_schema: res.inferred_schema,
          stats: res.stats,
          ddl_schema: res.ddl_schema,
        } : null,
        configureResult: res.config ? { ok: true, message: 'Restored' } : null,
        validateResult: res.validation as ValidateResponse | null,
        transformResult: res.transform as TransformResponse | null,
        loadResult: res.load_result as LoadResponse | null,
        statsResult: null,
      })
    } catch (err) {
      setOpenError(err instanceof Error ? err.message : 'Failed to resume project')
    } finally {
      setResumingId(null)
    }
  }

  async function handleRename(projectId: string) {
    if (!renameValue.trim()) return
    try {
      const updated = await renameProject(projectId, renameValue.trim())
      setProjects(prev => prev?.map(p => p.id === projectId ? updated : p) ?? null)
      setRenamingId(null)
    } catch (err) {
      setOpenError(err instanceof Error ? err.message : 'Failed to rename project')
    }
  }

  async function handleDelete(projectId: string) {
    if (!confirm('Delete this project? This cannot be undone.')) return
    try {
      await deleteProject(projectId)
      setProjects(prev => prev?.filter(p => p.id !== projectId) ?? null)
    } catch (err) {
      setOpenError(err instanceof Error ? err.message : 'Failed to delete project')
    }
  }

  function formatDate(dateStr: string) {
    try {
      return new Date(dateStr).toLocaleDateString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    } catch {
      return dateStr
    }
  }

  const inputClasses = 'rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50'
  const buttonClasses = 'px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed'

  return (
    <div className="flex flex-col items-center justify-center min-h-screen p-6 relative z-[5]">
      {/* Header */}
      <div className="text-center mb-10">
        <h1 className="text-4xl font-bold text-foreground flex items-center justify-center gap-2">
          <span className="inline-flex items-center justify-center w-10 h-10 rounded-lg bg-primary text-primary-foreground text-lg font-bold">
            E
          </span>
          TL Legacy
        </h1>
        <p className="text-muted-foreground mt-2 text-sm">Legacy Data Pipeline Toolkit</p>
      </div>

      {/* Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 w-full max-w-3xl mb-6">
        <Card
          className={`cursor-pointer transition-all hover:border-primary/60 ${selection === 'create' ? 'border-primary ring-2 ring-primary/30' : ''}`}
          onClick={() => handleSelect('create')}
        >
          <CardContent className="flex flex-col items-center gap-3 pt-6 pb-4">
            <FolderPlus className="h-8 w-8 text-primary" />
            <span className="text-sm font-medium text-foreground">Create Project</span>
          </CardContent>
        </Card>

        <Card
          className={`cursor-pointer transition-all hover:border-accent/60 ${selection === 'open' ? 'border-accent ring-2 ring-accent/30' : ''}`}
          onClick={() => handleSelect('open')}
        >
          <CardContent className="flex flex-col items-center gap-3 pt-6 pb-4">
            <FolderOpen className="h-8 w-8 text-accent" />
            <span className="text-sm font-medium text-foreground">Open Project</span>
          </CardContent>
        </Card>

        <Card
          className="cursor-pointer transition-all hover:border-yellow-500/60"
          onClick={() => dispatch({ type: 'START_GUEST' })}
        >
          <CardContent className="flex flex-col items-center gap-3 pt-6 pb-4">
            <Zap className="h-8 w-8 text-yellow-500" />
            <span className="text-sm font-medium text-foreground">Guest Session</span>
          </CardContent>
        </Card>
      </div>

      {/* Create Project Form */}
      {selection === 'create' && (
        <div className="w-full max-w-3xl rounded-lg border border-border bg-muted/50 p-6 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <input
              className={inputClasses}
              placeholder="Username"
              value={createUsername}
              onChange={e => setCreateUsername(e.target.value)}
            />
            <input
              className={inputClasses}
              placeholder="Project Name"
              value={createName}
              onChange={e => setCreateName(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-3">
            <button
              className={buttonClasses}
              disabled={createLoading || !createUsername.trim() || !createName.trim()}
              onClick={handleCreate}
            >
              {createLoading ? <Spinner size="sm" /> : 'Create'}
            </button>
            {createError && <p className="text-sm text-destructive">{createError}</p>}
          </div>
        </div>
      )}

      {/* Open Project Form */}
      {selection === 'open' && (
        <div className="w-full max-w-3xl rounded-lg border border-border bg-muted/50 p-6 space-y-4">
          <div className="flex gap-3">
            <input
              className={`${inputClasses} flex-1`}
              placeholder="Username"
              value={openUsername}
              onChange={e => setOpenUsername(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleLoadProjects()}
            />
            <button
              className={buttonClasses}
              disabled={openLoading || !openUsername.trim()}
              onClick={handleLoadProjects}
            >
              {openLoading ? <Spinner size="sm" /> : 'Load'}
            </button>
          </div>
          {openError && <p className="text-sm text-destructive">{openError}</p>}

          {projects !== null && (
            projects.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">No projects found for this user.</p>
            ) : (
              <div className="overflow-x-auto rounded-md border border-border bg-card">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-muted/50 border-b border-border">
                      <th className="px-3 py-2 text-left text-xs font-semibold text-primary uppercase tracking-wider">Project</th>
                      <th className="px-3 py-2 text-left text-xs font-semibold text-primary uppercase tracking-wider">Phase</th>
                      <th className="px-3 py-2 text-left text-xs font-semibold text-primary uppercase tracking-wider">Last Updated</th>
                      <th className="px-3 py-2 text-right text-xs font-semibold text-primary uppercase tracking-wider">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {projects.map(project => (
                      <tr
                        key={project.id}
                        className="border-b border-border/40 last:border-0 hover:bg-accent/10 transition-colors cursor-pointer"
                        onClick={() => !resumingId && !renamingId && handleResume(project)}
                      >
                        <td className="px-3 py-2 text-foreground">
                          {renamingId === project.id ? (
                            <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                              <input
                                className={`${inputClasses} w-40`}
                                value={renameValue}
                                onChange={e => setRenameValue(e.target.value)}
                                onKeyDown={e => {
                                  if (e.key === 'Enter') handleRename(project.id)
                                  if (e.key === 'Escape') setRenamingId(null)
                                }}
                                autoFocus
                              />
                              <button
                                className="p-1 rounded hover:bg-accent/20 text-accent"
                                onClick={() => handleRename(project.id)}
                              >
                                <Check className="h-4 w-4" />
                              </button>
                              <button
                                className="p-1 rounded hover:bg-muted text-muted-foreground"
                                onClick={() => setRenamingId(null)}
                              >
                                <X className="h-4 w-4" />
                              </button>
                            </div>
                          ) : (
                            <span className="font-medium">{project.name}</span>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <Badge variant="secondary">{project.phase}</Badge>
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {formatDate(project.updated_at)}
                        </td>
                        <td className="px-3 py-2 text-right" onClick={e => e.stopPropagation()}>
                          <div className="flex items-center justify-end gap-1">
                            {resumingId === project.id && <Spinner size="sm" />}
                            <button
                              className="p-1 rounded hover:bg-accent/20 text-muted-foreground hover:text-foreground"
                              onClick={() => {
                                setRenamingId(project.id)
                                setRenameValue(project.name)
                              }}
                            >
                              <Pencil className="h-4 w-4" />
                            </button>
                            <button
                              className="p-1 rounded hover:bg-destructive/20 text-muted-foreground hover:text-destructive"
                              onClick={() => handleDelete(project.id)}
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}
        </div>
      )}
    </div>
  )
}
