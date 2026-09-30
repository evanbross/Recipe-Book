import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { Search, Plus, BookOpen, Settings } from 'lucide-react'
import WatchlistAlert from './WatchlistAlert'
import styles from './Layout.module.css'

export default function Layout() {
  const [query, setQuery] = useState('')
  const navigate = useNavigate()

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
        </nav>
      </header>

      <WatchlistAlert />

      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  )
}
