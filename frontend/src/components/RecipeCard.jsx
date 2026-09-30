import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Clock, Globe, Camera, FileText, Mail, ImagePlus } from 'lucide-react'
import ImagePickerDialog from './ImagePickerDialog'
import styles from './RecipeCard.module.css'

const SOURCE_ICON = {
  web: Globe,
  image: Camera,
  manual: FileText,
  email: Mail,
}

function sourceName(recipe) {
  if (recipe.source_type === 'email') return 'Email'
  if (recipe.source_type === 'image') return 'Photo'
  if (recipe.source_url) {
    try {
      return new URL(recipe.source_url).hostname.replace(/^www\./, '')
    } catch {
      return null
    }
  }
  return null
}

export default function RecipeCard({ recipe }) {
  const [showPicker, setShowPicker] = useState(false)

  const Icon = SOURCE_ICON[recipe.source_type] || FileText
  const displayImage = recipe.thumbnail_url || recipe.image_url
  const label = sourceName(recipe)
  const isPending = recipe.image_pending && !displayImage

  const handlePickerClick = (e) => {
    e.preventDefault()
    e.stopPropagation()
    setShowPicker(true)
  }

  return (
    <>
      <Link to={`/recipes/${recipe.id}`} className={`card ${styles.card}`}>
        <div className={styles.imageWrap}>
          {displayImage
            ? <img src={displayImage} alt={recipe.title} className={styles.image} />
            : <div className={styles.imagePlaceholder}><FileText size={32} /></div>
          }

          {isPending && (
            <button
              type="button"
              className={styles.pendingBtn}
              onClick={handlePickerClick}
              title="Pick an image for this recipe"
              aria-label="Choose recipe image"
            >
              <ImagePlus size={14} />
              <span>Choose image</span>
            </button>
          )}

          <span className={`${styles.sourceTag} ${label ? styles.sourceTagLabel : ''}`} title={recipe.source_type}>
            <Icon size={12} />
            {label && <span>{label}</span>}
          </span>
        </div>

        <div className={styles.body}>
          <h3 className={styles.title}>{recipe.title}</h3>

          {recipe.description && (
            <p className={styles.description}>{recipe.description}</p>
          )}

          <div className={styles.meta}>
            {recipe.prep_time && (
              <span className={styles.metaItem}>
                <Clock size={12} /> {recipe.prep_time}
              </span>
            )}
          </div>

          {recipe.tags.length > 0 && (
            <div className={styles.tags}>
              {recipe.tags.slice(0, 4).map(tag => (
                <span key={tag.id} className="tag-chip">{tag.name}</span>
              ))}
              {recipe.tags.length > 4 && (
                <span className="tag-chip">+{recipe.tags.length - 4}</span>
              )}
            </div>
          )}
        </div>
      </Link>

      {showPicker && (
        <ImagePickerDialog
          recipe={recipe}
          onClose={() => setShowPicker(false)}
        />
      )}
    </>
  )
}
