import { Linkedin, Github } from 'lucide-react'

export function Footer() {
  return (
    <footer className="border-t border-white/5 py-6 px-6">
      <div className="mx-auto max-w-7xl flex items-center justify-center gap-3">
        <span className="text-sm text-slate-500">Created by Simran Kaur</span>
        <a
          href="https://www.linkedin.com/in/-kaur-simran"
          target="_blank"
          rel="noopener noreferrer"
          className="text-slate-500 hover:text-accent transition-colors"
          aria-label="LinkedIn"
        >
          <Linkedin className="w-4 h-4" />
        </a>
        <a
          href="https://github.com/skaur47"
          target="_blank"
          rel="noopener noreferrer"
          className="text-slate-500 hover:text-slate-200 transition-colors"
          aria-label="GitHub"
        >
          <Github className="w-4 h-4" />
        </a>
      </div>
    </footer>
  )
}
