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
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { KeyRound } from 'lucide-react'
import { SIGN_IN_URL, passwordLogin } from '../api/client'
import { isPasskeyCancelled, passkeysSupported, signInWithPasskey } from '../api/passkeys'
import { ME_QUERY_KEY, useMe } from '../api/useMe'
import AuthCard from '../components/AuthCard'
import { messageForCode, messageForError } from '../utils/authMessages'
import styles from './Login.module.css'

/** Sign in with a password, a passkey or Google. Google errors arrive as ?error=<code>. */
export default function Login() {
  const [params] = useSearchParams()
  const { data: me } = useMe()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const redirectError = params.get('error')

  if (me) return <Navigate to="/" replace />

  const signedIn = async () => {
    await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY })
    navigate('/', { replace: true })
  }

  const attempt = async (signIn) => {
    setBusy(true)
    setError(null)
    try {
      await signIn()
      await signedIn()
    } catch (err) {
      if (!isPasskeyCancelled(err)) setError(messageForError(err))
    } finally {
      setBusy(false)
    }
  }

  const handlePassword = (e) => {
    e.preventDefault()
    if (email.trim() && password) attempt(() => passwordLogin(email.trim(), password))
  }

  return (
    <AuthCard error={error ?? (redirectError ? messageForCode(redirectError) : null)}>
      <form className={styles.form} onSubmit={handlePassword}>
        <label className={styles.field}>
          Email
          <input
            className="input" type="email" autoComplete="username webauthn" required
            value={email} onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label className={styles.field}>
          Password
          <input
            className="input" type="password" autoComplete="current-password" required
            value={password} onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <button type="submit" className={`btn btn-primary ${styles.wide}`} disabled={busy}>Sign in</button>
      </form>

      <div className={styles.divider}>or</div>

      {passkeysSupported() && (
        <button
          type="button" className={`btn btn-secondary ${styles.wide}`} disabled={busy}
          onClick={() => attempt(signInWithPasskey)}
        >
          <KeyRound size={15} /> Sign in with a passkey
        </button>
      )}
      <a className={`btn btn-secondary ${styles.wide}`} href={SIGN_IN_URL}>Sign in with Google</a>

      <div className={styles.links}>
        <Link to="/forgot-password">Forgot password?</Link>
        <Link to="/register">Create an account</Link>
      </div>
    </AuthCard>
  )
}
