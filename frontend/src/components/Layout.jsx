import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Search, Plus, BookOpen, Settings, LogOut } from 'lucide-react'
import { logout } from '../api/client'
import { useMe } from '../api/useMe'
import WatchlistAlert from './WatchlistAlert'
import styles from './Layout.module.css'

export default function Layout() {
  const [query, setQuery] = useState('')
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: me } = useMe()

  // ai: claude-opus-5-5 | 2026-11-17
  const handleSignOut = async () => {
    try {
      await logout()
    } catch (err) {
      toast.error(`Sign-out failed: ${err.response?.status ?? 'server unreachable'}`)
      return
    }
    qc.clear()   // drop every cached query: it belonged to the signed-out user
    navigate('/login', { replace: true })
  }

  const handleSearch = (e) => {
    e.preventDefault()
    if (query.trim()) navigate(`/search?q=${encodeURIComponent(query.trim())}`)
  }

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <NavLink to="/" className={styles.logo}>
          <BookOpen size={22} />
          <span>RecipeBox</span>
        </NavLink>

        <form className={styles.searchForm} onSubmit={handleSearch}>
          <Search size={16} className={styles.searchIcon} />
          <input
            className={styles.searchInput}
            type="search"
            placeholder="Search recipes…"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
        </form>

        <nav className={styles.nav}>
          <NavLink to="/search" className={styles.navLink}>Browse</NavLink>
          <NavLink to="/add" className={`btn btn-primary ${styles.addBtn}`}>
            <Plus size={16} /> Add Recipe
          </NavLink>
          <NavLink to="/settings" className={styles.settingsLink} title="Settings">
            <Settings size={19} />
          </NavLink>
          {me && (
            <span className={styles.userName} title={me.user.email}>
              {me.user.display_name || me.user.email}
            </span>
          )}
          <button type="button" className={styles.settingsLink} onClick={handleSignOut} title="Sign out" aria-label="Sign out">
            <LogOut size={18} />
          </button>
        </nav>
      </header>

      <WatchlistAlert />

      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  )
}
