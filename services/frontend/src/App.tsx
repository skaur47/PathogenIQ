import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Nav } from './components/Nav'
import { HomePage } from './pages/HomePage'
import { CurrentNewsPage } from './pages/CurrentNewsPage'
import { TrendsPage } from './pages/TrendsPage'
import { GraphPage } from './pages/GraphPage'
import { AboutPage } from './pages/AboutPage'
import { ContactPage } from './pages/ContactPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 2 * 60 * 1000,
      retry: 2,
    },
  },
})

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Nav />
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/news" element={<CurrentNewsPage />} />
          <Route path="/trends" element={<TrendsPage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/contact" element={<ContactPage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
