export interface PathogenProfile {
  species_name: string
  common_name: string | null
  category: string
  genome_type: string | null
  transmission_routes: string[] | null
  reservoir_hosts: string[] | null
  description: string | null
  who_priority: boolean
  ncbi_taxonomy_id: string | null
}

export interface PathogensResponse {
  pathogens: PathogenProfile[]
  total: number
}

export interface ResearchArticle {
  pmid: string | null
  title: string
  authors: string | null
  published_date: string | null
  article_category: string
  gathered_by: string
  source_url: string | null
  article_summary: string | null
}

export interface PathogenResearch {
  pathogen_name: string
  overall_summary: string | null
  molecular_biology_summary: string | null
  experiments_summary: string | null
  therapeutics_summary: string | null
  clinical_epi_summary: string | null
  infection_mechanism_summary: string | null
  wet_lab_summary: string | null
  clinical_trial_summary: string | null
  vaccine_therapy_summary: string | null
  article_count: number
  last_researched_at: string | null
  articles: ResearchArticle[]
}

export interface PathogenHypothesis {
  pathogen_name: string
  research_gap: string | null
  proposed_strategy: string | null
  wetlab_experiments: string | null
  clinical_approaches: string | null
  rationale: string | null
  overall_recommendation: string | null
  last_synthesized_at: string | null
}

export interface DocumentSourceItem {
  document_id: string
  title: string | null
  url: string | null
  source: string
  published_date: string | null
  mention_count: number
}

export interface PathogenSources {
  pathogen_name: string
  total_documents: number
  documents: DocumentSourceItem[]
}

export interface GraphNode {
  id: string
  label: string
  type: 'Pathogen' | 'Category' | 'ReservoirHost' | 'TransmissionRoute'
  // D3 simulation fields (mutated by d3-force)
  x?: number
  y?: number
  vx?: number
  vy?: number
  fx?: number | null
  fy?: number | null
}

export interface GraphEdge {
  source: string | GraphNode
  target: string | GraphNode
  type: string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface PipelineStatus {
  last_research_run_at: string | null
  last_hypothesis_run_at: string | null
  last_ingested_at: string | null
  total_pathogens: number
  total_documents: number
  total_research_articles: number
}

export interface TriggerResponse {
  job_id: string
  agent: string
  message: string
}

export interface JobStatusResponse {
  job_id: string
  status: string
  result?: Record<string, unknown>
}

export interface PipelineRunningResponse {
  running: boolean
  job_id: string | null
}

export interface DocumentItem {
  id: string
  source: string
  external_id: string
  title: string | null
  abstract: string | null
  url: string | null
  published_date: string | null
  status: string
  created_at: string
}

export interface DocumentListResponse {
  items: DocumentItem[]
  total: number
  limit: number
  offset: number
}

export interface PathogenDaySeries {
  pathogen_name: string
  counts: number[]
}

export interface PathogenTrendsData {
  dates: string[]
  series: PathogenDaySeries[]
}
