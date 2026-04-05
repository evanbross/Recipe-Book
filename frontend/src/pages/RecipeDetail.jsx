import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { ArrowLeft, Clock, Users, Globe, Trash2 } from 'lucide-react'
import { getRecipe, deleteRecipe } from '../api/client'
import styles from './RecipeDetail.module.css'

export default function RecipeDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: recipe, isLoading } = useQuery({
    queryKey: ['recipe', id],
    queryFn: () => getRecipe(id),
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteRecipe(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['recipes'] })
      toast.success('Recipe deleted')
      navigate('/')
    },
    onError: () => toast.error('Delete failed'),
  })

  const confirmDelete = () => {
    if (window.confirm('Delete this recipe? This cannot be undone.')) {
      deleteMutation.mutate()
    }
  }

  if (isLoading) return <div className="loading-spinner"><div className="spinner" /></div>
  if (!recipe) return <div className="page-container"><p>Recipe not found.</p></div>

  const ingredients = recipe.ingredients?.split('\n').filter(Boolean) ?? []
  const instructions = recipe.instructions?.split('\n').filter(Boolean) ?? []

  return (
    <div className="page-container">
      <div className={styles.topBar}>
        <Link to="/" className="btn btn-ghost"><ArrowLeft size={16} /> Back</Link>
        <div className={styles.actions}>
          {recipe.source_url && (
            <a href={recipe.source_url} target="_blank" rel="noopener noreferrer" className="btn btn-secondary">
              <Globe size={15} /> Source
            </a>
          )}
          <button className={`btn btn-ghost ${styles.deleteBtn}`} onClick={confirmDelete}>
            <Trash2 size={15} /> Delete
          </button>
        </div>
      </div>

      <div className={styles.layout}>
        <div className={styles.content}>
          <h1 className={styles.title}>{recipe.title}</h1>

          {recipe.description && <p className={styles.description}>{recipe.description}</p>}

          <div className={styles.meta}>
            {recipe.prep_time && <span><Clock size={14} /> Prep: {recipe.prep_time}</span>}
            {recipe.cook_time && <span><Clock size={14} /> Cook: {recipe.cook_time}</span>}
            {recipe.servings  && <span><Users size={14} /> {recipe.servings}</span>}
          </div>

          {recipe.tags.length > 0 && (
            <div className={styles.tags}>
              {recipe.tags.map(tag => (
                <Link key={tag.id} to={`/search?tags=${tag.slug}`} className="tag-chip">
                  {tag.name}
                </Link>
              ))}
            </div>
          )}

          <div className={styles.sections}>
            {ingredients.length > 0 && (
              <section>
                <h2 className={styles.sectionHead}>Ingredients</h2>
                <ul className={styles.ingredientList}>
                  {ingredients.map((line, i) => <li key={i}>{line}</li>)}
                </ul>
              </section>
            )}

            {instructions.length > 0 && (
              <section>
                <h2 className={styles.sectionHead}>Instructions</h2>
                <ol className={styles.instructionList}>
                  {instructions.map((step, i) => <li key={i}>{step}</li>)}
                </ol>
              </section>
            )}
          </div>
        </div>

        {recipe.image_url && (
          <aside className={styles.imagePanel}>
            <img src={recipe.image_url} alt={recipe.title} className={styles.image} />
          </aside>
        )}
      </div>
    </div>
  )
}
