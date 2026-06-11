import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Nav } from './components/Nav'
import { Footer } from './components/Footer'
import { HomePage } from './pages/HomePage'
import { CurrentNewsPage } from './pages/CurrentNewsPage'
import { ResearchPage } from './pages/ResearchPage'
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
          <Route path="/research" element={<ResearchPage />} />
          <Route path="/trends" element={<TrendsPage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/contact" element={<ContactPage />} />
        </Routes>
        <Footer />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
