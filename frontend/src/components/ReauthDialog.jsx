/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-19
import { useEffect, useState } from 'react'
import { KeyRound, X } from 'lucide-react'
import { GOOGLE_REAUTH_URL, reauthPassword } from '../api/client'
import { isPasskeyCancelled, passkeysSupported, reauthWithPasskey } from '../api/passkeys'
import { messageForError } from '../utils/authMessages'
import styles from './ReauthDialog.module.css'

/** "Confirm it's you": offers each method the user has. Calls onConfirmed once
 *  the server has restarted the re-auth window. Google leaves the page and
 *  comes back to /settings?reauth=ok, so it can't call onConfirmed. */
export default function ReauthDialog({ methods, onConfirmed, onClose }) {
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const canUsePasskey = methods.passkeys.length > 0 && passkeysSupported()

  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = previous }
  }, [])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const confirm = async (prove) => {
    setBusy(true)
    setError(null)
    try {
      await prove()
    } catch (err) {
      if (!isPasskeyCancelled(err)) setError(messageForError(err))
      setBusy(false)
      return
    }
    setBusy(false)
    onConfirmed()
  }

  const handlePassword = (e) => {
    e.preventDefault()
    if (password) confirm(() => reauthPassword(password))
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div
        className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="reauth-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.header}>
          <h2 id="reauth-title" className={styles.title}>Confirm it&apos;s you</h2>
          <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className={styles.body}>
          <p className={styles.hint}>Changing how you sign in needs a fresh check, good for 10 minutes.</p>
          {error && <p className={styles.error} role="alert">{error}</p>}

          {methods.has_password && (
            <form className={styles.form} onSubmit={handlePassword}>
              <input
                className="input" type="password" autoComplete="current-password" placeholder="Your password"
                aria-label="Your password" value={password} onChange={(e) => setPassword(e.target.value)}
              />
              <button type="submit" className="btn btn-primary" disabled={busy || !password}>Confirm</button>
            </form>
          )}
          {canUsePasskey && (
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => confirm(reauthWithPasskey)}>
              <KeyRound size={15} /> Use a passkey
            </button>
          )}
          {methods.google.length > 0 && (
            <a className="btn btn-secondary" href={GOOGLE_REAUTH_URL}>Continue with Google</a>
          )}
        </div>
      </div>
    </div>
  )
}
