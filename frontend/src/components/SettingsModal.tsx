import { useEffect, useState } from 'react'
import { api, type AppSettings } from '../api'

const PROVIDER_FIELDS: { provider: string; label: string }[] = [
  { provider: 'fireworks', label: 'Fireworks' },
  { provider: 'openai', label: 'OpenAI' },
  { provider: 'anthropic', label: 'Anthropic' },
]

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        setSettings(s)
        setValues(s.values)
      })
      .catch((e) => setError(e.message))
  }, [])

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const updated = await api.updateSettings(values)
      setSettings(updated)
      setValues(updated.values)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const field = (key: string, label: string, secret = false) => (
    <label className="settings-field" key={key}>
      <span>{label}</span>
      <input
        type={secret ? 'password' : 'text'}
        value={values[key] ?? ''}
        placeholder={secret ? 'not set' : ''}
        onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
      />
    </label>
  )

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Settings</h2>
        {!settings && !error && <p>Loading…</p>}
        {error && <p className="error">{error}</p>}
        {settings && (
          <>
            <label className="settings-field">
              <span>Default provider</span>
              <select
                value={values.default_provider ?? 'fireworks'}
                onChange={(e) => setValues((v) => ({ ...v, default_provider: e.target.value }))}
              >
                {PROVIDER_FIELDS.map((p) => (
                  <option key={p.provider} value={p.provider}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            {PROVIDER_FIELDS.map(({ provider, label }) => (
              <fieldset key={provider}>
                <legend>{label}</legend>
                {field(`${provider}_api_key`, 'API key', true)}
                {field(`${provider}_smart_model`, 'Smart model')}
                {field(`${provider}_fast_model`, 'Fast model')}
              </fieldset>
            ))}
            <fieldset>
              <legend>Tools</legend>
              {field('exa_api_key', 'Exa API key (web search)', true)}
            </fieldset>
            <div className="modal-actions">
              <button onClick={onClose}>Cancel</button>
              <button className="primary" onClick={save} disabled={saving}>
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
