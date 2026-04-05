import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { getRecipes } from '../api/client'
import RecipeCard from '../components/RecipeCard'
import styles from './Home.module.css'

export default function Home() {
  const { data: recipes = [], isLoading } = useQuery({
    queryKey: ['recipes'],
    queryFn: () => getRecipes({ limit: 24 }),
  })

  return (
    <div className="page-container">
      <div className={styles.hero}>
        <h1 className={styles.heroTitle}>Your Recipe Collection</h1>
        <p className={styles.heroSub}>
          Capture recipes from the web, photos, or scans — organized your way.
        </p>
        <Link to="/add" className="btn btn-primary">
          <Plus size={18} /> Add Your First Recipe
        </Link>
      </div>

      {isLoading && (
        <div className="loading-spinner"><div className="spinner" /></div>
      )}

      {!isLoading && recipes.length === 0 && (
        <div className="empty-state">
          <h3>No recipes yet</h3>
          <p>Start by adding a recipe from a web page, photo, or scan.</p>
        </div>
      )}

      {recipes.length > 0 && (
        <>
          <h2 className="section-title">Recently Added</h2>
          <div className={styles.grid}>
            {recipes.map(recipe => (
              <RecipeCard key={recipe.id} recipe={recipe} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
