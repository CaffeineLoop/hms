import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/useAuth'
import { Icon } from '../components/icons/Icon'
import { Alert, Button, Field, Input } from '../components/ui'
import './LoginPage.css'

export function LoginPage() {
  const { status, login, sessionEndedReason } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (status === 'signed-in') return <Navigate to={from} replace />

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!username.trim() || !password) {
      setError('Enter your username and password.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await login(username.trim(), password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Sign-in failed. Please try again.')
      setPassword('')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login">
      <section className="login__brand" aria-hidden="true">
        <div className="login__brand-inner">
          <div className="login__logo">
            <svg viewBox="0 0 32 32" width="40" height="40"><rect width="32" height="32" rx="7" fill="#1b7f95" /><path d="M13 8h6v5h5v6h-5v5h-6v-5H8v-6h5z" fill="#fff" /></svg>
            <span>HMS</span>
          </div>
          <h2 className="login__headline">Clinical records, diagnostics and care workflows — in one secure system.</h2>
          <ul className="login__points">
            <li><Icon name="shieldCheck" size={18} /> Role-based access with a complete audit trail</li>
            <li><Icon name="document" size={18} /> Every entry attributed to the clinician who made it</li>
            <li><Icon name="ai" size={18} /> AI analysis is read-only and always requires clinician review</li>
          </ul>
        </div>
      </section>

      <main className="login__panel">
        <form className="login__form" onSubmit={onSubmit} noValidate aria-labelledby="login-title">
          <div>
            <h1 id="login-title" className="login__title">Sign in</h1>
            <p className="login__subtitle">Use your HMS staff account.</p>
          </div>
          {sessionEndedReason && !error ? <Alert tone="info">{sessionEndedReason}</Alert> : null}
          {error ? <Alert tone="danger">{error}</Alert> : null}
          <Field label="Username" required>
            <Input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus
              icon="user" />
          </Field>
          <Field label="Password" required>
            <Input type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} icon="lock" />
          </Field>
          <Button type="submit" variant="primary" size="lg" block loading={submitting}>Sign in</Button>
          <p className="login__footnote">
            Access is restricted to authorised hospital staff. Sign-in attempts are recorded.
          </p>
        </form>
      </main>
    </div>
  )
}
