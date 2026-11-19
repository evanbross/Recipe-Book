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
import { useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Check, KeyRound, Pencil, Plus, ShieldCheck, X } from 'lucide-react'
import {
  GOOGLE_LINK_URL, getSignInMethods, removePasskey, removePassword, renamePasskey, setPassword, unlinkIdentity,
} from '../api/client'
import { addPasskey, isPasskeyCancelled, passkeysSupported } from '../api/passkeys'
import ReauthDialog from '../components/ReauthDialog'
import { isReauthRequired, messageForCode, messageForError } from '../utils/authMessages'
import settingsStyles from './Settings.module.css'
import styles from './SignInMethodsSection.module.css'

const SIGN_IN_METHODS_KEY = ['signInMethods']

const formatDate = (iso) => new Date(iso).toLocaleDateString()

/** Notes for the query string Google flows come back to /settings with. */
function returnNotice(params) {
  if (params.get('reauth') === 'ok') return { kind: 'ok', text: "Thanks, that's confirmed. Please do what you were doing again." }
  if (params.get('linked') === 'google') return { kind: 'ok', text: 'Google account linked. You can now sign in with it.' }
  if (params.get('error')) return { kind: 'error', text: messageForCode(params.get('error')) }
  return null
}

/** Settings: the password, passkeys and Google accounts this user signs in with. */
export default function SignInMethodsSection() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const { data: methods } = useQuery({ queryKey: SIGN_IN_METHODS_KEY, queryFn: getSignInMethods })
  const [busy, setBusy] = useState(false)
  // An action the server refused with reauth_required, retried once after the dialog.
  const [pending, setPending] = useState(null)
  const [newPassword, setNewPassword] = useState('')
  const [showPasswordForm, setShowPasswordForm] = useState(false)
  const [renaming, setRenaming] = useState(null)   // { id, name } while a passkey is being renamed

  const notice = returnNotice(params)
  const methodCount = methods ? Number(methods.has_password) + methods.passkeys.length + methods.google.length : 0
  const onlyOne = methodCount <= 1

  const refresh = () => qc.invalidateQueries({ queryKey: SIGN_IN_METHODS_KEY })

  const run = async (action, { retrying = false } = {}) => {
    setBusy(true)
    try {
      await action.run()
      if (action.success) toast.success(action.success)
      await refresh()
    } catch (err) {
      if (isReauthRequired(err) && !retrying) setPending(action)
      else if (!isPasskeyCancelled(err)) toast.error(messageForError(err))
    } finally {
      setBusy(false)
    }
  }

  const perform = (actionRun, success) => run({ run: actionRun, success })

  const handleConfirmed = () => {
    const action = pending
    setPending(null)
    run(action, { retrying: true })
  }

  const dismissNotice = () => setParams({}, { replace: true })

  const handleSetPassword = (e) => {
    e.preventDefault()
    if (!newPassword) return
    perform(async () => {
      await setPassword(newPassword)
      setNewPassword('')
      setShowPasswordForm(false)
    }, methods.has_password ? 'Password changed. Other browsers were signed out.' : 'Password set.')
  }

  const handleRemovePassword = () => {
    if (window.confirm('Remove your password? You will sign in with your passkeys or Google instead.')) {
      perform(removePassword, 'Password removed.')
    }
  }

  const handleAddPasskey = () => perform(() => addPasskey(), 'Passkey added.')

  const handleRename = (e) => {
    e.preventDefault()
    const name = renaming.name.trim()
    if (!name) return
    perform(async () => {
      await renamePasskey(renaming.id, name)
      setRenaming(null)
    }, 'Passkey renamed.')
  }

  const handleRemovePasskey = (passkey) => {
    if (window.confirm(`Remove the passkey "${passkey.name}"? It won't sign you in any more.`)) {
      perform(() => removePasskey(passkey.id), 'Passkey removed.')
    }
  }

  const handleLinkGoogle = () => {
    const go = async () => { window.location.assign(GOOGLE_LINK_URL) }
    // A full-page navigation can't show the re-auth dialog afterwards, so check first.
    if (Date.now() < Date.parse(methods.reauth_valid_until)) go()
    else setPending({ run: go, success: null })
  }

  const handleUnlink = (identity) => {
    if (window.confirm(`Unlink the Google account ${identity.email}? It won't sign you in any more.`)) {
      perform(() => unlinkIdentity(identity.id), 'Google account unlinked.')
    }
  }

  return (
    <section className={settingsStyles.section}>
      <h2 className={settingsStyles.sectionTitle}><ShieldCheck size={17} /> Sign-in methods</h2>
      <div className={settingsStyles.card}>
        {notice && (
          <p className={notice.kind === 'ok' ? styles.noticeOk : styles.noticeError} role="status">
            <span>{notice.text}</span>
            <button type="button" className={styles.iconBtn} onClick={dismissNotice} aria-label="Dismiss">
              <X size={14} />
            </button>
          </p>
        )}

        {methods && (
          <>
            {/* ── Password ── */}
            <div className={styles.group}>
              <h3 className={styles.groupTitle}>Password</h3>
              <div className={styles.row}>
                <span className={styles.what}>{methods.has_password ? 'A password is set.' : 'No password.'}</span>
                <button
                  type="button" className="btn btn-secondary" disabled={busy}
                  onClick={() => setShowPasswordForm((v) => !v)}
                >
                  {methods.has_password ? 'Change' : 'Set a password'}
                </button>
                {methods.has_password && (
                  <button
                    type="button" className="btn btn-ghost" disabled={busy || onlyOne} onClick={handleRemovePassword}
                    title={onlyOne ? "It's your only way to sign in" : undefined}
                  >
                    Remove
                  </button>
                )}
              </div>
              {showPasswordForm && (
                <form className={styles.inlineForm} onSubmit={handleSetPassword}>
                  <input
                    className="input" type="password" autoComplete="new-password" minLength={12} maxLength={256}
                    placeholder="New password (12+ characters)" aria-label="New password"
                    value={newPassword} onChange={(e) => setNewPassword(e.target.value)}
                  />
                  <button type="submit" className="btn btn-primary" disabled={busy || !newPassword}>Save</button>
                </form>
              )}
            </div>

            {/* ── Passkeys ── */}
            <div className={styles.group}>
              <h3 className={styles.groupTitle}>Passkeys</h3>
              {methods.passkeys.length === 0 && <p className={styles.muted}>No passkeys yet.</p>}
              <ul className={styles.list} aria-label="Passkeys">
                {methods.passkeys.map((p) => (
                  <li key={p.id} className={styles.row}>
                    {renaming?.id === p.id ? (
                      <form className={styles.inlineForm} onSubmit={handleRename}>
                        <input
                          className="input" maxLength={100} aria-label="Passkey name" autoFocus
                          value={renaming.name} onChange={(e) => setRenaming({ id: p.id, name: e.target.value })}
                        />
                        <button type="submit" className={styles.iconBtn} disabled={busy} aria-label="Save name">
                          <Check size={14} />
                        </button>
                        <button type="button" className={styles.iconBtn} onClick={() => setRenaming(null)} aria-label="Cancel rename">
                          <X size={14} />
                        </button>
                      </form>
                    ) : (
                      <>
                        <span className={styles.what}>
                          <KeyRound size={14} /> {p.name}
                          <span className={styles.muted}>
                            {' '}added {formatDate(p.created_at)}
                            {p.last_used_at ? `, last used ${formatDate(p.last_used_at)}` : ', never used'}
                          </span>
                        </span>
                        <button
                          type="button" className={styles.iconBtn} disabled={busy}
                          onClick={() => setRenaming({ id: p.id, name: p.name })} aria-label={`Rename ${p.name}`}
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button" className={styles.iconBtn} disabled={busy || onlyOne}
                          onClick={() => handleRemovePasskey(p)} aria-label={`Remove ${p.name}`}
                        >
                          <X size={14} />
                        </button>
                      </>
                    )}
                  </li>
                ))}
              </ul>
              {passkeysSupported() ? (
                <button type="button" className="btn btn-secondary" disabled={busy} onClick={handleAddPasskey}>
                  <Plus size={14} /> Add a passkey
                </button>
              ) : (
                <p className={styles.muted}>This browser can&apos;t create passkeys.</p>
              )}
            </div>

            {/* ── Google ── */}
            <div className={styles.group}>
              <h3 className={styles.groupTitle}>Google accounts</h3>
              {methods.google.length === 0 && <p className={styles.muted}>No Google account linked.</p>}
              <ul className={styles.list} aria-label="Google accounts">
                {methods.google.map((g) => (
                  <li key={g.id} className={styles.row}>
                    <span className={styles.what}>
                      {g.email} <span className={styles.muted}>linked {formatDate(g.created_at)}</span>
                    </span>
                    <button
                      type="button" className={styles.iconBtn} disabled={busy || onlyOne}
                      onClick={() => handleUnlink(g)} aria-label={`Unlink ${g.email}`}
                    >
                      <X size={14} />
                    </button>
                  </li>
                ))}
              </ul>
              <button type="button" className="btn btn-secondary" disabled={busy} onClick={handleLinkGoogle}>
                <Plus size={14} /> Link a Google account
              </button>
            </div>
          </>
        )}
      </div>

      {pending && methods && (
        <ReauthDialog methods={methods} onConfirmed={handleConfirmed} onClose={() => setPending(null)} />
      )}
    </section>
  )
}
