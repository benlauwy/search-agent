import { useMemo, useRef, useState } from 'react'
import type { FileInfo } from '../api'

// Keep in sync with backend TEXT_EXTENSIONS: text files only for now.
export const ACCEPTED_EXTENSIONS =
  '.txt,.md,.markdown,.csv,.tsv,.json,.yaml,.yml,.xml,.html,.py,.js,.ts,.log'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function groupVersions(files: FileInfo[]): { latest: FileInfo; older: FileInfo[] }[] {
  const byName = new Map<string, FileInfo[]>()
  for (const f of files) {
    const list = byName.get(f.filename) ?? []
    list.push(f)
    byName.set(f.filename, list)
  }
  return Array.from(byName.values()).map((list) => {
    const sorted = [...list].sort((a, b) => b.version - a.version)
    return { latest: sorted[0], older: sorted.slice(1) }
  })
}

export function FilesPanel({
  files,
  onUpload,
  readOnly = false,
}: {
  files: FileInfo[]
  onUpload: (file: File) => Promise<void>
  readOnly?: boolean
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const uploads = files.filter((f) => f.kind === 'upload')
  const artifactGroups = useMemo(
    () => groupVersions(files.filter((f) => f.kind === 'artifact')),
    [files],
  )

  const toggleExpanded = (filename: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(filename)) next.delete(filename)
      else next.add(filename)
      return next
    })
  }

  const handleFiles = async (list: FileList | null) => {
    if (!list?.length) return
    setUploading(true)
    setError(null)
    try {
      for (const file of Array.from(list)) {
        await onUpload(file)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const fileRow = (f: FileInfo, label?: string) => (
    <a key={f.id} className="file-row" href={`/api/files/${f.id}/download`} download={f.filename}>
      <span className="file-name">{label ?? f.filename}</span>
      <span className="file-meta">
        v{f.version} · {formatSize(f.size)}
      </span>
    </a>
  )

  const artifactGroup = ({ latest, older }: { latest: FileInfo; older: FileInfo[] }) => (
    <div key={latest.filename} className="file-group">
      {fileRow(latest)}
      {older.length > 0 && (
        <>
          <button className="version-toggle" onClick={() => toggleExpanded(latest.filename)}>
            {expanded.has(latest.filename) ? '▾' : '▸'} {older.length} older version
            {older.length > 1 ? 's' : ''}
          </button>
          {expanded.has(latest.filename) && (
            <div className="version-list">{older.map((f) => fileRow(f))}</div>
          )}
        </>
      )}
    </div>
  )

  return (
    <div className="files-panel">
      <div className="files-section">
        <div className="files-header">
          <h3>Uploads</h3>
          {!readOnly && (
            <button onClick={() => inputRef.current?.click()} disabled={uploading}>
              {uploading ? 'Uploading…' : '+ Upload'}
            </button>
          )}
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED_EXTENSIONS}
            multiple
            hidden
            onChange={(e) => void handleFiles(e.target.files)}
          />
        </div>
        {error && <div className="error">{error}</div>}
        {uploads.length === 0 ? (
          <p className="muted">Text files only for now.</p>
        ) : (
          uploads.map((f) => fileRow(f))
        )}
      </div>
      <div className="files-section">
        <h3>Artifacts</h3>
        {artifactGroups.length === 0 ? (
          <p className="muted">Files the agent writes appear here.</p>
        ) : (
          artifactGroups.map(artifactGroup)
        )}
      </div>
    </div>
  )
}
