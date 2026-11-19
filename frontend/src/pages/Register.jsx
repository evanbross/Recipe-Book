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
import { register } from '../api/client'
import AuthCard from '../components/AuthCard'
import { messageForError } from '../utils/authMessages'
import styles from './Login.module.css'

/** Create a password account. The account only exists once the emailed link is
 *  followed, and the reply never says whether the address already had one. */
export default function Register() {
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [sentTo, setSentTo] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await register(email.trim(), password, displayName.trim())
      setSentTo(email.trim())
    } catch (err) {
      setError(messageForError(err))
    } finally {
      setBusy(false)
    }
  }

  if (sentTo) {
    return (
      <AuthCard title="Check your email">
        <p className={styles.hint}>
          We sent a message to <strong>{sentTo}</strong>. Follow the link in it to finish signing up.
          It may take a minute to arrive; check your spam folder too.
        </p>
        <Link to="/login">Back to sign in</Link>
      </AuthCard>
    )
  }

  return (
    <AuthCard title="Create an account" error={error}>
      <form className={styles.form} onSubmit={handleSubmit}>
        <label className={styles.field}>
          Email
          <input
            className="input" type="email" autoComplete="email" required
            value={email} onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label className={styles.field}>
          Your name (optional)
          <input
            className="input" type="text" autoComplete="name" maxLength={200}
            value={displayName} onChange={(e) => setDisplayName(e.target.value)}
          />
        </label>
        <label className={styles.field}>
          Password
          <input
            className="input" type="password" autoComplete="new-password" required minLength={12} maxLength={256}
            value={password} onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <p className={styles.hint}>At least 12 characters. A few unrelated words make a good one.</p>
        <button type="submit" className={`btn btn-primary ${styles.wide}`} disabled={busy}>Create account</button>
      </form>
      <div className={styles.links}><Link to="/login">I already have an account</Link></div>
    </AuthCard>
  )
}
