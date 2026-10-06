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

/** A paper on an island's page; `released` when the island has let it go. */
export interface IslandPaper extends Paper {
  selected_by?: string | null;
  released?: boolean | null;
  /** The island's readers' joint decision: true kept, false turned down, null while they read. */
  kept?: boolean | null;
}

/** Likes within a view, keyed `kind:id`: how many, and from which islands. */
export type Likes = Record<string, { count: number; islands: string[] }>;

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
  research_methods?: {
    version: number;
    domain: string;
    specialist: boolean;
    instructions: string;
    sources: { title: string; url: string }[];
  } | Record<string, never>;
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
  stats?: { runs?: number | null; completed?: number | null } | null;
  /** Likes on the agent's work and on papers it voted to keep. */
  points?: number | null;
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
  /** Whether this reader voted to keep the paper. */
  keep?: boolean | null;
  summary: string;
  thesis_quote?: string | null;
  thesis_char_start?: number | null;
  thesis_char_end?: number | null;
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
  /** The stored event payload, when the server includes it for detailed replay. */
  payload?: unknown;
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
  papers: IslandPaper[];
  runs: Run[];
  cost_micros?: Micros | null;
  month_cost_micros?: Micros | null;
  budget_share?: number | null;
  runs_remaining_today?: number | null;
  evolution?: EvolutionStep[] | null;
  /** The island's own switches, and the operator's switch for every island. */
  evolution_enabled?: boolean | null;
  mutation_enabled?: boolean | null;
  swarm_evolution_enabled?: boolean | null;
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
  likes?: Likes | null;
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
  likes?: Likes | null;
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

/** One criterion of the public brief's grade: its weight, its 0-100 score and the numbers behind it. */
export interface GradeCriterion {
  criterion: string;
  weight: number;
  score: number;
  measured: boolean;
  evidence: string;
}

export interface Grade {
  letter: string;
  score: number;
  criteria: GradeCriterion[];
  caps: { ceiling: string; reason: string }[];
  rule: string;
}

export interface BriefClaim {
  text: string;
  paper_id: string;
  paper_title: string;
  agent: string;
  island_id: string;
  reading_id: string;
  depends_on_paper: boolean;
  /** The reading agent's own label: whether the claim credits, describes or doubts the paper. */
  stance?: "positive" | "neutral" | "negative" | null;
  verified: boolean;
  quote?: string | null;
  created_at: number;
}

/** A selected paper or one awaiting its reader cohort. */
export interface BriefPaper {
  id: string;
  title: string;
  primary_category: string;
  text_status: string;
  first_seen_at: number;
  islands: string[];
  readings: number;
  runs: number;
  days_left?: number | null;
  let_go_after?: number | null;
  /** For a selected paper: the newest reading's thesis quote and its biggest takeaways. */
  thesis?: string | null;
  takeaways?: string[] | null;
  /** The public record of the paper and all its readings. */
  href?: string | null;
  /** In `recent_papers`: whether readers or a person selected it. The field keeps its legacy API name. */
  held?: boolean | null;
  kept_by?: string[];
}

export interface BriefAgent {
  address: string;
  island_id: string;
  version: number;
  generation: number;
  runs: number;
  completed: number;
  failed: number;
  reading_now?: { run_id: string; paper_id: string; paper_title: string } | null;
}

export type BriefNumbers = Record<string, number | { reason: string; n: number }[]>;

export interface BriefIsland {
  id: string;
  name: string;
  focus: string;
  agents: number;
  evolve: boolean;
  paused: boolean;
  numbers: BriefNumbers;
}

export interface BriefGeneration {
  island_id: string;
  generation: number;
  status: string;
  reason?: string | null;
  decisions: { genome_id?: string; decision?: string; reason?: string; usefulness?: number }[];
  created_at: number;
}

/** `GET /public/brief`: the swarm told in words and numbers, with a grade. */
export interface Brief {
  generated_at: number;
  about?: string;
  grade?: Grade;
  findings?: string[];
  numbers?: BriefNumbers;
  islands?: BriefIsland[];
  agents?: BriefAgent[];
  claims?: BriefClaim[];
  papers?: {
    held: number;
    waiting: number;
    released?: number;
    let_go_after_days: number;
    rule: string;
    held_papers: BriefPaper[];
    waiting_papers: BriefPaper[];
    /** The newest selected or waiting papers. */
    recent_papers?: BriefPaper[];
  };
  evolution?: BriefGeneration[];
  limits?: string[];
}

/** One step of `GET /public/activity`: who did what to which paper, and which others it looked at. */
export interface ActivityStep {
  id: number;
  run_id: string;
  agent: string;
  island_id: string;
  paper_id: string;
  kind: string;
  tool?: string | null;
  passage_id?: string | null;
  looked_at: string[];
  /** When it happened, as ISO-8601 UTC, e.g. `2026-10-02T16:09:23Z`. */
  created_at: string;
}

export interface ActivityPaper {
  id: string;
  title: string;
  primary_category: string;
  islands: string[];
}

export interface Activity {
  steps: ActivityStep[];
  papers: Record<string, ActivityPaper>;
  last_id: number;
}
