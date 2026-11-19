/*!
 * Copyright (c) 2026 ZombieTech LLC. All rights reserved.
 *
 * SPDX-License-Identifier: PolyForm-Strict-1.0.0
 * See LICENSE in the project root for the full terms.
 *
 * Licensing inquiries: license@zombietech.biz
 */
// ai: claude-opus-5-5 | 2026-11-19
import { BookOpen } from 'lucide-react'
import styles from './AuthCard.module.css'

/** The centred card every signed-out page (sign in, register, reset...) sits in. */
export default function AuthCard({ title, error, notice, children }) {
  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.logo}><BookOpen size={26} /> RecipeBox</div>
        {title && <h1 className={styles.title}>{title}</h1>}
        {error && <p className={styles.error} role="alert">{error}</p>}
        {notice && <p className={styles.notice} role="status">{notice}</p>}
        {children}
      </div>
    </div>
  )
}
