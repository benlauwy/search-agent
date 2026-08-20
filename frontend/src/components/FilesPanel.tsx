import { useRef, useState } from 'react'
import type { FileInfo } from '../api'

// Keep in sync with backend TEXT_EXTENSIONS: text files only for now.
export const ACCEPTED_EXTENSIONS =
  '.txt,.md,.markdown,.csv,.tsv,.json,.yaml,.yml,.xml,.html,.py,.js,.ts,.log'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function FilesPanel({
  files,
  onUpload,
}: {
  files: FileInfo[]
  onUpload: (file: File) => Promise<void>
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const uploads = files.filter((f) => f.kind === 'upload')
  const artifacts = files.filter((f) => f.kind === 'artifact')

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

  const fileRow = (f: FileInfo) => (
    <a key={f.id} className="file-row" href={`/api/files/${f.id}/download`} download={f.filename}>
      <span className="file-name">{f.filename}</span>
      <span className="file-meta">
        v{f.version} · {formatSize(f.size)}
      </span>
    </a>
  )

  return (
    <div className="files-panel">
      <div className="files-section">
        <div className="files-header">
          <h3>Uploads</h3>
          <button onClick={() => inputRef.current?.click()} disabled={uploading}>
            {uploading ? 'Uploading…' : '+ Upload'}
          </button>
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
        {uploads.length === 0 ? <p className="muted">Text files only for now.</p> : uploads.map(fileRow)}
      </div>
      <div className="files-section">
        <h3>Artifacts</h3>
        {artifacts.length === 0 ? (
          <p className="muted">Files the agent writes appear here.</p>
        ) : (
          artifacts.map(fileRow)
        )}
      </div>
    </div>
  )
}
