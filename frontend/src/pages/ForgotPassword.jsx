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
import { Link } from 'react-router-dom'
import { forgotPassword } from '../api/client'
import AuthCard from '../components/AuthCard'
import { messageForError } from '../utils/authMessages'
import styles from './Login.module.css'

/** Ask for a reset link. The reply is the same whether or not the address has an account. */
export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [sent, setSent] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await forgotPassword(email.trim())
      setSent(true)
    } catch (err) {
      setError(messageForError(err))
    } finally {
      setBusy(false)
    }
  }

  if (sent) {
    return (
      <AuthCard title="Check your email">
        <p className={styles.hint}>
          If <strong>{email.trim()}</strong> has an account, we&apos;ve sent it a link to set a new
          password. The link works for one hour.
        </p>
        <Link to="/login">Back to sign in</Link>
      </AuthCard>
    )
  }

  return (
    <AuthCard title="Forgot your password?" error={error}>
      <form className={styles.form} onSubmit={handleSubmit}>
        <label className={styles.field}>
          Email
          <input
            className="input" type="email" autoComplete="email" required
            value={email} onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <button type="submit" className={`btn btn-primary ${styles.wide}`} disabled={busy}>Send reset link</button>
      </form>
      <div className={styles.links}><Link to="/login">Back to sign in</Link></div>
    </AuthCard>
  )
}
