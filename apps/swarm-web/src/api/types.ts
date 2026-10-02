// What the swarm server answers, as API.md records it. A field marked optional is one the page
// reads when the server sends it and reports as not available when it does not.

/** Money in millionths of a US dollar. */
export type Micros = number;

export type BudgetMode = "normal" | "conserving" | "hard stop" | "stored-data only";

export interface Budget {
  target_micros?: Micros | null;
  month_to_date_micros?: Micros | null;
  projected_month_micros?: Micros | null;
  mode?: string | null;
}

export interface Island {
  id: string;
  name: string;
  focus: string;
  created_at: number;
  paper_count?: number | null;
  run_count?: number | null;
}

export interface Storm {
  islands: Island[];
  papers: number;
  runs: number;
  cost_micros: Micros;
  budget?: Budget | null;
}

/** Where in the paper an event read: a page, a section, a quoted passage, or any of them. */
export interface Locator {
  page?: number | null;
  section?: string | null;
  quote?: string | null;
}

export interface PaperSection {
  id?: string | null;
  title: string;
  page?: number | null;
  text: string;
}

export interface Paper {
  id: string;
  title: string;
  summary: string;
  url: string;
  primary_category: string;
  text_status: string;
  fetched_at: number;
  pdf_url?: string | null;
  sections?: PaperSection[] | null;
  cost_micros?: Micros | null;
}

export interface Assignment {
  paper_id: string;
  island_id: string;
  reason: string;
}

export interface Genome {
  id: string;
  island_id: string;
  prompt: string;
  /** Tool names, comma separated. */
  tools: string;
  parent_id: string | null;
  generation: number;
  active: number;
  created_at: number;
  cost_micros?: Micros | null;
}

export interface Run {
  id: string;
  paper_id: string;
  island_id: string;
  genome_id: string;
  status: string;
  reading: string;
  created_at: number;
  cost_micros?: Micros | null;
}

export interface RunEvent {
  id: number;
  run_id: string;
  kind: string;
  body: string;
  cost_micros: Micros;
  created_at: number;
  tool?: string | null;
  model?: string | null;
  /** What the agent asked the tool or the model at this step. */
  input?: string | null;
  /** What came back. */
  output?: string | null;
  locator?: Locator | null;
}

/** One genome decision of one evolution cycle. */
export interface EvolutionStep {
  generation: number;
  genome_id: string;
  decision: string;
  reason?: string | null;
}

export interface IslandView {
  island: Island;
  papers: Paper[];
  genomes: Genome[];
  runs: Run[];
  cost_micros: Micros;
  month_cost_micros?: Micros | null;
  budget_share?: number | null;
  runs_remaining_today?: number | null;
  evolution?: EvolutionStep[] | null;
}

export interface PaperView {
  paper: Paper;
  assignments: Assignment[];
  runs: Run[];
  cost_micros: Micros;
  cost_by_island?: Record<string, Micros> | null;
}

export interface RunView {
  run: Run;
  events: RunEvent[];
  cost_micros: Micros;
  genome?: Genome | null;
  paper?: Paper | null;
}

export interface ChatLink {
  id: string;
  title?: string | null;
  kind?: "paper" | "run" | "island" | null;
}

export interface ChatAnswer {
  answer: string;
  links: ChatLink[];
  cost_micros?: Micros | null;
  answer_id?: string | null;
}

export interface LoginAnswer {
  island: string;
  token: string;
}
