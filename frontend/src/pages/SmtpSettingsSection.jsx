/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { MailCheck, Save, Send } from 'lucide-react'
import ReauthDialog from '../components/ReauthDialog'
import {
  getSignInMethods, getSmtpSettings, testSmtpSettings, updateSmtpSettings,
} from '../api/client'
import { useMe } from '../api/useMe'
import { isReauthRequired } from '../utils/authMessages'
import styles from './Settings.module.css'

const SMTP_KEY = ['admin', 'smtp']

// ai: gpt-5 | 2026-11-21
export default function SmtpSettingsSection() {
  const qc = useQueryClient()
  const { data: me } = useMe()
  const isAdmin = me?.is_admin === true
  const { data: smtp } = useQuery({ queryKey: SMTP_KEY, queryFn: getSmtpSettings, enabled: isAdmin })
  const { data: methods } = useQuery({
    queryKey: ['signInMethods'], queryFn: getSignInMethods, enabled: isAdmin,
  })
  const [form, setForm] = useState({ host: '', port: '587', user: '', password: '', use_tls: true, from_address: '' })
  const [reauthAction, setReauthAction] = useState(null)
  const initialized = useRef(false)

  useEffect(() => {
    if (!smtp || initialized.current) return
    initialized.current = true
    setForm({
      host: smtp.host, port: String(smtp.port), user: smtp.user, password: '',
      use_tls: smtp.use_tls, from_address: smtp.from_address,
    })
  }, [smtp])

  const handleProtectedError = (err, action, fallback) => {
    if (isReauthRequired(err)) {
      setReauthAction(action)
    } else {
      toast.error(err.response?.data?.detail === 'email_failed' ? 'The SMTP server rejected the test email.' : fallback)
    }
  }

  const save = useMutation({
    mutationFn: updateSmtpSettings,
    onSuccess: (saved) => {
      qc.setQueryData(SMTP_KEY, saved)
      setForm((current) => ({ ...current, password: '' }))
      toast.success('Outgoing mail settings saved.')
    },
    onError: (err, payload) => handleProtectedError(
      err, { type: 'save', payload }, 'Could not save outgoing mail settings.',
    ),
  })

  const test = useMutation({
    mutationFn: testSmtpSettings,
    onSuccess: () => toast.success(`Test email sent to ${me.user.email}.`),
    onError: (err) => handleProtectedError(err, { type: 'test' }, 'Could not send the test email.'),
  })

  const handleSave = (e) => {
    e.preventDefault()
    const port = Number(form.port)
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      toast.error('Enter a port from 1 to 65535.')
      return
    }
    save.mutate({
      ...form, port, password: form.password || null,
      host: form.host.trim(), user: form.user.trim(), from_address: form.from_address.trim(),
    })
  }

  const afterReauth = () => {
    const action = reauthAction
    setReauthAction(null)
    if (action?.type === 'save') save.mutate(action.payload)
    if (action?.type === 'test') test.mutate()
  }

  if (!isAdmin) return null

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}><MailCheck size={17} /> Outgoing Mail</h2>
      <div className={styles.card}>
        <p className={styles.adminDesc}>
          Server-wide SMTP relay for account verification and password resets.
          Current source: <strong>{smtp?.source ?? 'loading'}</strong>.
        </p>
        <form className={styles.settingsForm} onSubmit={handleSave}>
          <div className={styles.fieldRow}>
            <label className={styles.fieldLabel} htmlFor="smtp-host">SMTP host</label>
            <input id="smtp-host" className="input" required value={form.host}
              onChange={(e) => setForm({ ...form, host: e.target.value })} />
          </div>
          <div className={styles.fieldRow}>
            <label className={styles.fieldLabel} htmlFor="smtp-port">Port</label>
            <input id="smtp-port" className={`input ${styles.fieldInputShort}`} type="number" min="1" max="65535" required
              value={form.port} onChange={(e) => setForm({ ...form, port: e.target.value })} />
          </div>
          <div className={styles.fieldRow}>
            <label className={styles.fieldLabel} htmlFor="smtp-user">Username</label>
            <input id="smtp-user" className="input" autoComplete="username" value={form.user}
              onChange={(e) => setForm({ ...form, user: e.target.value })} />
          </div>
          <div className={styles.fieldRow}>
            <label className={styles.fieldLabel} htmlFor="smtp-password">Password</label>
            <input id="smtp-password" className="input" type="password" autoComplete="new-password"
              placeholder={smtp?.password_set ? 'Saved — leave blank to keep' : 'SMTP password'} value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </div>
          <div className={styles.fieldRow}>
            <label className={styles.fieldLabel} htmlFor="smtp-from">From address</label>
            <input id="smtp-from" className="input" type="email" required value={form.from_address}
              onChange={(e) => setForm({ ...form, from_address: e.target.value })} />
          </div>
          <label className={styles.checkRow}>
            <input type="checkbox" checked={form.use_tls}
              onChange={(e) => setForm({ ...form, use_tls: e.target.checked })} />
            <span><strong>Use STARTTLS</strong></span>
          </label>
          <div className={styles.smtpActions}>
            <button className="btn btn-primary" type="submit" disabled={save.isPending || !smtp}>
              <Save size={14} /> Save settings
            </button>
            <button className="btn btn-secondary" type="button" disabled={test.isPending || !smtp}
              onClick={() => test.mutate()}>
              <Send size={14} /> Send test to {me.user.email}
            </button>
          </div>
        </form>
      </div>
      {reauthAction && methods && (
        <ReauthDialog methods={methods} onConfirmed={afterReauth} onClose={() => setReauthAction(null)} />
      )}
    </section>
  )
}
