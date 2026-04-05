import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDropzone } from 'react-dropzone'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Globe, Camera, FileText, Upload } from 'lucide-react'
import { captureFromUrl, captureFromImage, createRecipe } from '../api/client'
import TagPicker from '../components/TagPicker'
import styles from './AddRecipe.module.css'

const TABS = [
  { id: 'url',    label: 'From Web URL',  Icon: Globe },
  { id: 'image',  label: 'From Image',    Icon: Camera },
  { id: 'manual', label: 'Manual Entry',  Icon: FileText },
]

export default function AddRecipe() {
  const [tab, setTab] = useState('url')
  const [tagIds, setTagIds] = useState([])
  const navigate = useNavigate()
  const qc = useQueryClient()

  // ── URL capture ────────────────────────────────────────────────────────
  const [url, setUrl] = useState('')
  const urlMutation = useMutation({
    mutationFn: () => captureFromUrl({ url, tag_ids: tagIds }),
    onSuccess: (recipe) => {
      qc.invalidateQueries({ queryKey: ['recipes'] })
      toast.success('Recipe captured!')
      navigate(`/recipes/${recipe.id}`)
    },
    onError: (e) => toast.error(e?.response?.data?.detail || 'Capture failed'),
  })

  // ── Image capture ──────────────────────────────────────────────────────
  const [file, setFile] = useState(null)
  const onDrop = useCallback((accepted) => { if (accepted[0]) setFile(accepted[0]) }, [])
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'image/*': [] },
    maxFiles: 1,
  })
  const imageMutation = useMutation({
    mutationFn: () => captureFromImage(file, tagIds),
    onSuccess: (recipe) => {
      qc.invalidateQueries({ queryKey: ['recipes'] })
      toast.success('Recipe extracted!')
      navigate(`/recipes/${recipe.id}`)
    },
    onError: (e) => toast.error(e?.response?.data?.detail || 'Extraction failed'),
  })

  // ── Manual entry ───────────────────────────────────────────────────────
  const [form, setForm] = useState({
    title: '', description: '', ingredients: '',
    instructions: '', servings: '', prep_time: '', cook_time: '',
  })
  const manualMutation = useMutation({
    mutationFn: () => createRecipe({ ...form, tag_ids: tagIds, source_type: 'manual' }),
    onSuccess: (recipe) => {
      qc.invalidateQueries({ queryKey: ['recipes'] })
      toast.success('Recipe saved!')
      navigate(`/recipes/${recipe.id}`)
    },
    onError: () => toast.error('Save failed'),
  })

  const isLoading = urlMutation.isPending || imageMutation.isPending || manualMutation.isPending

  return (
    <div className="page-container">
      <h1 className="section-title">Add a Recipe</h1>

      <div className={styles.layout}>
        <div className={styles.main}>
          {/* Tab bar */}
          <div className={styles.tabs}>
            {TABS.map(({ id, label, Icon }) => (
              <button
                key={id}
                type="button"
                className={`${styles.tab} ${tab === id ? styles.activeTab : ''}`}
                onClick={() => setTab(id)}
              >
                <Icon size={15} /> {label}
              </button>
            ))}
          </div>

          {/* URL tab */}
          {tab === 'url' && (
            <div className={styles.panel}>
              <label className={styles.label}>Recipe page URL</label>
              <input
                className="input"
                type="url"
                placeholder="https://www.example.com/recipe/..."
                value={url}
                onChange={e => setUrl(e.target.value)}
              />
              <p className={styles.hint}>
                Claude will fetch the page and extract the recipe automatically.
              </p>
              <button
                className="btn btn-primary"
                disabled={!url.trim() || isLoading}
                onClick={() => urlMutation.mutate()}
              >
                {isLoading ? 'Capturing…' : 'Capture Recipe'}
              </button>
            </div>
          )}

          {/* Image tab */}
          {tab === 'image' && (
            <div className={styles.panel}>
              <div
                {...getRootProps()}
                className={`${styles.dropzone} ${isDragActive ? styles.dropping : ''} ${file ? styles.hasFile : ''}`}
              >
                <input {...getInputProps()} />
                {file
                  ? <><img src={URL.createObjectURL(file)} alt="preview" className={styles.preview} /><p>{file.name}</p></>
                  : <><Upload size={32} /><p>Drop a photo or scan here, or click to select</p></>
                }
              </div>
              <p className={styles.hint}>
                Supports JPG, PNG, WebP. Claude will read and extract the recipe.
              </p>
              <button
                className="btn btn-primary"
                disabled={!file || isLoading}
                onClick={() => imageMutation.mutate()}
              >
                {isLoading ? 'Extracting…' : 'Extract Recipe'}
              </button>
            </div>
          )}

          {/* Manual tab */}
          {tab === 'manual' && (
            <div className={styles.panel}>
              {[
                ['title', 'Title *', 'text', 'e.g. Miso Ramen'],
                ['description', 'Description', 'text', 'A brief note about this recipe'],
                ['servings', 'Servings', 'text', 'e.g. 4 servings'],
                ['prep_time', 'Prep Time', 'text', 'e.g. 15 minutes'],
                ['cook_time', 'Cook Time', 'text', 'e.g. 30 minutes'],
              ].map(([field, label, type, placeholder]) => (
                <div key={field} className={styles.field}>
                  <label className={styles.label}>{label}</label>
                  <input
                    className="input"
                    type={type}
                    placeholder={placeholder}
                    value={form[field]}
                    onChange={e => setForm(f => ({ ...f, [field]: e.target.value }))}
                  />
                </div>
              ))}

              {['ingredients', 'instructions'].map(field => (
                <div key={field} className={styles.field}>
                  <label className={styles.label}>{field.charAt(0).toUpperCase() + field.slice(1)}</label>
                  <textarea
                    className={`input ${styles.textarea}`}
                    placeholder={field === 'ingredients' ? 'One ingredient per line…' : 'Step-by-step instructions…'}
                    value={form[field]}
                    onChange={e => setForm(f => ({ ...f, [field]: e.target.value }))}
                  />
                </div>
              ))}

              <button
                className="btn btn-primary"
                disabled={!form.title.trim() || isLoading}
                onClick={() => manualMutation.mutate()}
              >
                {isLoading ? 'Saving…' : 'Save Recipe'}
              </button>
            </div>
          )}
        </div>

        {/* Tag picker sidebar */}
        <aside className={styles.sidebar}>
          <h3 className={styles.sidebarTitle}>Tags</h3>
          <TagPicker selectedIds={tagIds} onChange={setTagIds} />
        </aside>
      </div>
    </div>
  )
}
