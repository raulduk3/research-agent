// What the swarm server answers (deploy/beta/README.md), as far as the pages read it. A field
// marked optional may be absent or null; the page then says it was not reported.

/** Money in millionths of a US dollar. */
export type Micros = number;

export type BudgetMode = "normal" | "conserving" | "hard stop" | "stored-data only";

/** The block every answer carries beside its data. */
export interface Budget {
  target_micros?: Micros | null;
  month_to_date_micros?: Micros | null;
  projected_month_micros?: Micros | null;
  mode?: string | null;
  runs_allowed?: boolean | null;
  runs_refusal?: string | null;
}

export interface Island {
  id: string;
  name: string;
  focus: string;
  /** Whether evolution may change this island's agents. */
  evolve?: boolean | null;
  state?: string | null;
  blocked_reason?: string | null;
  paper_count?: number | null;
  run_count?: number | null;
  agent_count?: number | null;
  cost_micros?: Micros | null;
}

export interface Storm {
  islands: Island[];
  papers: number;
  runs: number;
  cost_micros: Micros;
  budget?: Budget | null;
}

/** Where in the paper a step read. `section` is the id of the stored passage. */
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
  run_count?: number | null;
}

export interface Assignment {
  paper_id: string;
  island_id: string;
  reason: string;
}

/** What an agent is on right now. */
export interface CurrentRun {
  run_id: string;
  paper_id: string;
  paper_title: string;
  status: string;
}

/**
 * An agent: a genome seated on an island. The island view sends `parent_id` and `generation`
 * beside it; the copy a run kept carries them under `lineage` instead.
 */
export interface Agent {
  id: string;
  island_id: string;
  prompt: string;
  allowed_tools: string[];
  reading_strategy?: string | null;
  active: boolean;
  version?: number | null;
  parent_id?: string | null;
  generation?: number | null;
  lineage?: { generation?: number | null; parent?: { genome_id?: string | null } | null } | null;
  state?: string | null;
  blocked_reason?: string | null;
  current?: CurrentRun | null;
  stats?: { runs?: number | null; completed?: number | null; accepted?: number | null } | null;
  cost_micros?: Micros | null;
}

/** A run as a list row; the run page's own `run` has the same fields and more. */
export interface Run {
  id: string;
  paper_id: string;
  paper_title?: string | null;
  island_id: string;
  genome_id: string;
  genome_version?: number | null;
  status: string;
  failure?: string | null;
  created_at: number;
  cost_micros?: Micros | null;
}

export interface Claim {
  text: string;
  evidence?: { quote: string; verified?: boolean | null }[] | null;
}

/** What a run submitted: the bounded reading of its paper. */
export interface Reading {
  id: string;
  run_id: string;
  genome_id: string;
  summary: string;
  claims: Claim[];
  objections: string[];
  related_papers: string[];
  idea_seeds: string[];
  created_at: number;
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

/** One decision of one evolution cycle; a skipped cycle names no agent. */
export interface EvolutionStep {
  generation: number;
  genome_id: string | null;
  decision: string;
  reason?: string | null;
}

export interface IslandView {
  island: Island;
  agents: Agent[];
  queue?: Paper[] | null;
  papers: Paper[];
  runs: Run[];
  cost_micros?: Micros | null;
  month_cost_micros?: Micros | null;
  budget_share?: number | null;
  runs_remaining_today?: number | null;
  evolution?: EvolutionStep[] | null;
  /** Groups the server could not read; an empty list beside a name here is not "none". */
  unavailable?: string[] | null;
  budget?: Budget | null;
}

export interface PaperView {
  paper: Paper;
  assignments: Assignment[];
  runs: Run[];
  readings?: Reading[] | null;
  cost_micros?: Micros | null;
  cost_by_island?: Record<string, Micros> | null;
  unavailable?: string[] | null;
}

export interface RunView {
  run: Run;
  /** The genome exactly as the run used it, whatever has been edited since. */
  genome?: Agent | null;
  paper?: Paper | null;
  events: RunEvent[];
  reading?: Reading | null;
  cost_micros?: Micros | null;
}

/** The whole editable swarm spec, of which the pages read only the evolution switch. */
export interface SpecView {
  spec: { evolution?: { enabled?: boolean | null } | null };
}

export interface ChatLink {
  id: string;
  title?: string | null;
  kind?: string | null;
  snippet?: string | null;
}

export interface ChatAnswer {
  answer: string;
  links?: ChatLink[] | null;
  /** What this one answer cost; zero when it came from stored data alone. */
  cost_micros?: Micros | null;
  answer_id?: string | null;
  supported?: boolean | null;
}

export interface LoginAnswer {
  island: string | null;
  token: string;
  role?: string | null;
}
