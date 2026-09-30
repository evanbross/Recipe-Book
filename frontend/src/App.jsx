import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Home from './pages/Home'
import RecipeDetail from './pages/RecipeDetail'
import AddRecipe from './pages/AddRecipe'
import Search from './pages/Search'
import Settings from './pages/Settings'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="recipes/:id" element={<RecipeDetail />} />
          <Route path="add" element={<AddRecipe />} />
          <Route path="search" element={<Search />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
