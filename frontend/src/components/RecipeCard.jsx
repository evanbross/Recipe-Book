import { Link } from 'react-router-dom'
import { Clock, Globe, Camera, FileText } from 'lucide-react'
import styles from './RecipeCard.module.css'

const SOURCE_ICON = {
  web: Globe,
  image: Camera,
  manual: FileText,
}

export default function RecipeCard({ recipe }) {
  const Icon = SOURCE_ICON[recipe.source_type] || FileText

  return (
    <Link to={`/recipes/${recipe.id}`} className={`card ${styles.card}`}>
      <div className={styles.imageWrap}>
        {recipe.thumbnail_url
          ? <img src={recipe.thumbnail_url} alt={recipe.title} className={styles.image} />
          : <div className={styles.imagePlaceholder}><FileText size={32} /></div>
        }
        <span className={styles.sourceTag} title={recipe.source_type}>
          <Icon size={12} />
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
  )
}
