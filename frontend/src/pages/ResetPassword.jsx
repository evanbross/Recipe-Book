/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-19
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { resetPassword } from '../api/client'
import AuthCard from '../components/AuthCard'
import { messageForCode, messageForError } from '../utils/authMessages'
import styles from './Login.module.css'

/** The emailed reset link lands here. Posts only on submit, never on mount. */
export default function ResetPassword() {
  const [params] = useSearchParams()
  const token = params.get('token')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(token ? null : messageForCode('invalid_token'))
  const [done, setDone] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await resetPassword(token, password)
      setDone(true)
    } catch (err) {
      setError(messageForError(err))
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <AuthCard title="Password changed" notice="You've been signed out everywhere. Sign in with your new password.">
        <Link to="/login">Go to sign in</Link>
      </AuthCard>
    )
  }

  return (
    <AuthCard title="Choose a new password" error={error}>
      {token && (
        <form className={styles.form} onSubmit={handleSubmit}>
          <label className={styles.field}>
            New password
            <input
              className="input" type="password" autoComplete="new-password" required minLength={12} maxLength={256}
              value={password} onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <p className={styles.hint}>At least 12 characters.</p>
          <button type="submit" className={`btn btn-primary ${styles.wide}`} disabled={busy}>Set password</button>
        </form>
      )}
      <div className={styles.links}><Link to="/forgot-password">Send a new link</Link></div>
    </AuthCard>
  )
}
