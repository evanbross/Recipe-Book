import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { searchRecipes } from '../api/client'
import RecipeCard from '../components/RecipeCard'
import TagPicker from '../components/TagPicker'
import { Search as SearchIcon } from 'lucide-react'
import styles from './Search.module.css'

export default function Search() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [q, setQ] = useState(searchParams.get('q') || '')
  const [tagIds, setTagIds] = useState([])

  // Sync tag slugs from URL into IDs is deferred until tags load;
  // for simplicity we filter by tag IDs directly in the request.
  const tagSlugs = searchParams.get('tags') || ''

  const params = {
    q: searchParams.get('q') || '',
    tags: tagSlugs,
    page: 1,
    page_size: 24,
  }

  const { data, isLoading } = useQuery({
    queryKey: ['search', params],
    queryFn: () => searchRecipes(params),
  })

  const handleSearch = (e) => {
    e.preventDefault()
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (q.trim()) next.set('q', q.trim())
      else next.delete('q')
      return next
    })
  }

  return (
    <div className="page-container">
      <h1 className="section-title">Browse Recipes</h1>

      <div className={styles.layout}>
        {/* Sidebar filters */}
        <aside className={styles.sidebar}>
          <h3 className={styles.sidebarTitle}>Filter by Tag</h3>
          <TagPicker selectedIds={tagIds} onChange={setTagIds} />
        </aside>

        <div className={styles.main}>
          {/* Search bar */}
          <form className={styles.searchRow} onSubmit={handleSearch}>
            <div className={styles.searchWrap}>
              <SearchIcon size={16} className={styles.searchIcon} />
              <input
                className={`input ${styles.searchInput}`}
                type="search"
                placeholder="Search by title, ingredient, or keyword…"
                value={q}
                onChange={e => setQ(e.target.value)}
              />
            </div>
            <button type="submit" className="btn btn-primary">Search</button>
          </form>

          {/* Results */}
          {isLoading && <div className="loading-spinner"><div className="spinner" /></div>}

          {!isLoading && data && (
            <>
              <p className={styles.resultCount}>
                {data.total} recipe{data.total !== 1 ? 's' : ''} found
              </p>
              {data.results.length === 0
                ? (
                  <div className="empty-state">
                    <h3>No results</h3>
                    <p>Try different keywords or remove some filters.</p>
                  </div>
                )
                : (
                  <div className={styles.grid}>
                    {data.results.map(recipe => (
                      <RecipeCard key={recipe.id} recipe={recipe} />
                    ))}
                  </div>
                )
              }
            </>
          )}
        </div>
      </div>
    </div>
  )
}
