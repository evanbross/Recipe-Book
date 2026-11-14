import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getTags, getTagCategories } from '../api/client'
import { X } from 'lucide-react'
import styles from './TagPicker.module.css'

export default function TagPicker({ selectedIds = [], onChange }) {
  const [filter, setFilter] = useState('')

  const { data: categories = [] } = useQuery({
    queryKey: ['tag-categories'],
    queryFn: getTagCategories,
  })

  const { data: tags = [] } = useQuery({
    queryKey: ['tags'],
    queryFn: () => getTags(),
  })

  const filtered = tags.filter(t =>
    t.name.toLowerCase().includes(filter.toLowerCase())
  )

  // Group filtered tags by category
  const grouped = categories.map(cat => ({
    ...cat,
    tags: filtered.filter(t => t.category_id === cat.id),
  })).filter(cat => cat.tags.length > 0)

  const uncategorized = filtered.filter(t => !t.category_id)

  const toggle = (id) => {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter(i => i !== id))
    } else {
      onChange([...selectedIds, id])
    }
  }

  const selectedTags = tags.filter(t => selectedIds.includes(t.id))

  return (
    <div className={styles.wrapper}>
      {selectedTags.length > 0 && (
        <div className={styles.selected}>
          {selectedTags.map(tag => (
            <span key={tag.id} className={`tag-chip ${styles.selectedChip}`}>
              {tag.name}
              <button onClick={() => toggle(tag.id)} aria-label={`Remove ${tag.name}`}>
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      )}

      <input
        className="input"
        type="search"
        placeholder="Filter tags…"
        value={filter}
        onChange={e => setFilter(e.target.value)}
      />

      <div className={styles.list}>
        {grouped.map(cat => (
          <div key={cat.id} className={styles.group}>
            <div className={styles.groupLabel}>{cat.name}</div>
            <div className={styles.chips}>
              {cat.tags.map(tag => (
                <button
                  key={tag.id}
                  type="button"
                  className={`${styles.chip} ${selectedIds.includes(tag.id) ? styles.active : ''}`}
                  onClick={() => toggle(tag.id)}
                >
                  {tag.name}
                </button>
              ))}
            </div>
          </div>
        ))}
        {uncategorized.length > 0 && (
          <div className={styles.group}>
            <div className={styles.groupLabel}>Other</div>
            <div className={styles.chips}>
              {uncategorized.map(tag => (
                <button
                  key={tag.id}
                  type="button"
                  className={`${styles.chip} ${selectedIds.includes(tag.id) ? styles.active : ''}`}
                  onClick={() => toggle(tag.id)}
                >
                  {tag.name}
                </button>
              ))}
            </div>
          </div>
        )}
        {filtered.length === 0 && (
          <p className={styles.empty}>No tags match &ldquo;{filter}&rdquo;</p>
        )}
      </div>
    </div>
  )
}
