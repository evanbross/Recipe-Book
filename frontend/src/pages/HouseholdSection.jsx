/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-17
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Users, UserPlus, X } from 'lucide-react'
import { getHousehold, inviteToHousehold, removeHouseholdMember, revokeInvite } from '../api/client'
import { useMe } from '../api/useMe'
import settingsStyles from './Settings.module.css'
import styles from './HouseholdSection.module.css'

const HOUSEHOLD_KEY = ['household']

const apiError = (err, fallback) => err.response?.data?.detail ?? `${fallback} (${err.response?.status ?? 'server unreachable'})`

/** Settings section: who is in the household, and (for the owner) invites. */
export default function HouseholdSection() {
  const qc = useQueryClient()
  const { data: me } = useMe()
  const { data: household } = useQuery({ queryKey: HOUSEHOLD_KEY, queryFn: getHousehold })
  const [email, setEmail] = useState('')
  const isOwner = me?.role === 'owner'

  const refresh = () => qc.invalidateQueries({ queryKey: HOUSEHOLD_KEY })

  const invite = useMutation({
    mutationFn: inviteToHousehold,
    onSuccess: (created) => {
      setEmail('')
      toast.success(`Invited ${created.email}. They can now sign in with Google.`)
      refresh()
    },
    onError: (err) => toast.error(apiError(err, 'Invite failed')),
  })

  const revoke = useMutation({
    mutationFn: revokeInvite,
    onSuccess: refresh,
    onError: (err) => toast.error(apiError(err, 'Could not cancel the invite')),
  })

  const remove = useMutation({
    mutationFn: removeHouseholdMember,
    onSuccess: refresh,
    onError: (err) => toast.error(apiError(err, 'Could not remove the member')),
  })

  const handleInvite = (e) => {
    e.preventDefault()
    if (email.trim()) invite.mutate(email.trim())
  }

  const handleRemove = (member) => {
    const who = member.display_name || member.email
    if (window.confirm(`Remove ${who} from the household? They'll be signed out right away.`)) {
      remove.mutate(member.user_id)
    }
  }

  return (
    <section className={settingsStyles.section}>
      <h2 className={settingsStyles.sectionTitle}>
        <Users size={17} /> Household{household ? `: ${household.name}` : ''}
      </h2>
      <div className={settingsStyles.card}>
        <ul className={styles.list} aria-label="Members">
          {household?.members.map((m) => (
            <li key={m.user_id} className={styles.row}>
              <span className={styles.who}>
                {m.display_name || m.email}
                {m.display_name && <span className={styles.muted}> {m.email}</span>}
              </span>
              <span className={styles.role}>{m.role}</span>
              {isOwner && m.user_id !== me.user.id && (
                <button
                  type="button"
                  className={styles.iconBtn}
                  onClick={() => handleRemove(m)}
                  disabled={remove.isPending}
                  aria-label={`Remove ${m.email}`}
                >
                  <X size={14} />
                </button>
              )}
            </li>
          ))}
        </ul>

        {household?.invites.length > 0 && (
          <ul className={styles.list} aria-label="Pending invites">
            {household.invites.map((inv) => (
              <li key={inv.id} className={styles.row}>
                <span className={styles.who}>{inv.email}</span>
                <span className={styles.role}>invited</span>
                {isOwner && (
                  <button
                    type="button"
                    className={styles.iconBtn}
                    onClick={() => revoke.mutate(inv.id)}
                    disabled={revoke.isPending}
                    aria-label={`Cancel invite for ${inv.email}`}
                  >
                    <X size={14} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}

        {isOwner ? (
          <form className={styles.inviteForm} onSubmit={handleInvite}>
            <input
              className="input"
              type="email"
              placeholder="Email address to invite"
              aria-label="Email address to invite"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <button type="submit" className="btn btn-secondary" disabled={invite.isPending || !email.trim()}>
              <UserPlus size={15} /> Invite
            </button>
          </form>
        ) : (
          <p className={styles.muted}>Only the household owner can invite or remove people.</p>
        )}
      </div>
    </section>
  )
}
