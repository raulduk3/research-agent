import { z } from "zod";

export const microsSchema = z.number().int().nonnegative();

export const budgetModeSchema = z.union([
  z.literal("normal"),
  z.literal("conserving"),
  z.literal("hard stop"),
  z.literal("stored-data only"),
]);

export const budgetSchema = z.object({
  target_micros: microsSchema.optional().nullable(),
  month_to_date_micros: microsSchema.optional().nullable(),
  projected_month_micros: microsSchema.optional().nullable(),
  mode: z.string().optional().nullable(),
  runs_allowed: z.boolean().optional().nullable(),
  runs_refusal: z.string().optional().nullable(),
});

export const islandSchema = z.object({
  id: z.string(),
  name: z.string(),
  focus: z.string(),
  evolve: z.boolean().optional().nullable(),
  state: z.string().optional().nullable(),
  blocked_reason: z.string().optional().nullable(),
  paper_count: z.number().int().nonnegative().optional().nullable(),
  run_count: z.number().int().nonnegative().optional().nullable(),
  agent_count: z.number().int().nonnegative().optional().nullable(),
  cost_micros: microsSchema.optional().nullable(),
});

export const stormSchema = z.object({
  islands: z.array(islandSchema),
  papers: z.number().int().nonnegative(),
  runs: z.number().int().nonnegative(),
  cost_micros: microsSchema,
  budget: budgetSchema.optional().nullable(),
});

export const locatorSchema = z.object({
  page: z.number().optional().nullable(),
  section: z.string().optional().nullable(),
  quote: z.string().optional().nullable(),
});

export const paperSectionSchema = z.object({
  id: z.string().optional().nullable(),
  title: z.string(),
  page: z.number().optional().nullable(),
  text: z.string(),
});

export const paperSchema = z.object({
  id: z.string(),
  title: z.string(),
  summary: z.string(),
  url: z.string(),
  primary_category: z.string(),
  text_status: z.string(),
  fetched_at: z.number(),
  pdf_url: z.string().optional().nullable(),
  sections: z.array(paperSectionSchema).optional().nullable(),
  cost_micros: microsSchema.optional().nullable(),
  run_count: z.number().int().nonnegative().optional().nullable(),
});

export const islandPaperSchema = paperSchema.extend({
  selected_by: z.string().optional().nullable(),
  released: z.boolean().optional().nullable(),
  kept: z.boolean().optional().nullable(),
});

export const likesSchema = z.record(
  z.string(),
  z.object({
    count: z.number().int().nonnegative(),
    islands: z.array(z.string()),
  }),
);

export const assignmentSchema = z.object({
  paper_id: z.string(),
  island_id: z.string(),
  reason: z.string(),
  kept: z.boolean().optional().nullable(),
  released: z.boolean().optional().nullable(),
  selected_by: z.string().optional().nullable(),
});

export const currentRunSchema = z.object({
  run_id: z.string(),
  paper_id: z.string(),
  paper_title: z.string(),
  status: z.string(),
});

export const agentSchema = z.object({
  id: z.string(),
  island_id: z.string(),
  prompt: z.string(),
  research_methods: z
    .union([
      z.object({
        version: z.number().int().nonnegative(),
        domain: z.string(),
        specialist: z.boolean(),
        instructions: z.string(),
        sources: z.array(
          z.object({
            title: z.string(),
            url: z.string(),
          }),
        ),
      }),
      z.record(z.string(), z.never()),
    ])
    .optional(),
  allowed_tools: z.array(z.string()),
  reading_strategy: z.string().optional().nullable(),
  active: z.boolean(),
  version: z.number().int().nonnegative().optional().nullable(),
  parent_id: z.string().optional().nullable(),
  generation: z.number().int().nonnegative().optional().nullable(),
  lineage: z
    .object({
      parents: z.array(z.string()).optional().nullable(),
      generation: z.number().int().nonnegative().optional().nullable(),
      parent: z
        .object({
          genome_id: z.string().optional().nullable(),
        })
        .optional()
        .nullable(),
    })
    .optional()
    .nullable(),
  state: z.string().optional().nullable(),
  blocked_reason: z.string().optional().nullable(),
  current: currentRunSchema.optional().nullable(),
  stats: z
    .object({
      runs: z.number().int().nonnegative().optional().nullable(),
      completed: z.number().int().nonnegative().optional().nullable(),
    })
    .optional()
    .nullable(),
  points: z.number().int().nonnegative().optional().nullable(),
  cost_micros: microsSchema.optional().nullable(),
});

export const runSchema = z.object({
  id: z.string(),
  paper_id: z.string(),
  paper_title: z.string().optional().nullable(),
  island_id: z.string(),
  genome_id: z.string(),
  genome_version: z.number().int().nonnegative().optional().nullable(),
  status: z.string(),
  failure: z.string().optional().nullable(),
  created_at: z.number(),
  cost_micros: microsSchema.optional().nullable(),
});

export const claimSchema = z.object({
  text: z.string(),
  evidence: z
    .array(
      z.object({
        quote: z.string(),
        verified: z.boolean().optional().nullable(),
      }),
    )
    .optional()
    .nullable(),
});

export const readingSchema = z.object({
  id: z.string(),
  run_id: z.string(),
  genome_id: z.string(),
  keep: z.boolean().optional().nullable(),
  summary: z.string(),
  thesis_quote: z.string().optional().nullable(),
  thesis_char_start: z.number().optional().nullable(),
  thesis_char_end: z.number().optional().nullable(),
  claims: z.array(claimSchema),
  objections: z.array(z.string()),
  related_papers: z.array(z.string()),
  idea_seeds: z.array(z.string()),
  created_at: z.number(),
});

export const runEventSchema = z.object({
  id: z.number(),
  run_id: z.string(),
  kind: z.string(),
  body: z.string(),
  cost_micros: microsSchema,
  created_at: z.number(),
  tool: z.string().optional().nullable(),
  model: z.string().optional().nullable(),
  input: z.string().optional().nullable(),
  output: z.string().optional().nullable(),
  payload: z.unknown().optional(),
  locator: locatorSchema.optional().nullable(),
});

export const evolutionStepSchema = z.object({
  generation: z.number().int().nonnegative(),
  genome_id: z.string().nullable(),
  decision: z.string(),
  reason: z.string().optional().nullable(),
});

export const islandViewSchema = z.object({
  island: islandSchema,
  agents: z.array(agentSchema),
  queue: z.array(paperSchema).optional().nullable(),
  papers: z.array(islandPaperSchema),
  runs: z.array(runSchema),
  cost_micros: microsSchema.optional().nullable(),
  month_cost_micros: microsSchema.optional().nullable(),
  budget_share: z.number().optional().nullable(),
  runs_remaining_today: z.number().int().nonnegative().optional().nullable(),
  evolution: z.array(evolutionStepSchema).optional().nullable(),
  evolution_enabled: z.boolean().optional().nullable(),
  mutation_enabled: z.boolean().optional().nullable(),
  swarm_evolution_enabled: z.boolean().optional().nullable(),
  unavailable: z.array(z.string()).optional().nullable(),
  budget: budgetSchema.optional().nullable(),
});

export const paperViewSchema = z.object({
  paper: paperSchema,
  assignments: z.array(assignmentSchema),
  runs: z.array(runSchema),
  readings: z.array(readingSchema).optional().nullable(),
  cost_micros: microsSchema.optional().nullable(),
  cost_by_island: z.record(z.string(), microsSchema).optional().nullable(),
  likes: likesSchema.optional().nullable(),
  unavailable: z.array(z.string()).optional().nullable(),
});

export const costSummarySchema = z.discriminatedUnion("state", [
  z.object({ state: z.literal("unavailable") }),
  z.object({
    state: z.literal("available"),
    settled_micros: microsSchema,
    unsettled_micros: microsSchema,
    unsettled_count: z.number().int().nonnegative(),
  }),
]);

export const runViewSchema = z.object({
  cost: costSummarySchema.optional(),
  run: runSchema,
  genome: agentSchema.optional().nullable(),
  paper: paperSchema.optional().nullable(),
  events: z.array(runEventSchema),
  reading: readingSchema.optional().nullable(),
  cost_micros: microsSchema.optional().nullable(),
  likes: likesSchema.optional().nullable(),
});

export const chatLinkSchema = z.object({
  id: z.string(),
  title: z.string().optional().nullable(),
  kind: z.string().optional().nullable(),
  snippet: z.string().optional().nullable(),
});

export const chatAnswerSchema = z.object({
  answer: z.string(),
  links: z.array(chatLinkSchema).optional().nullable(),
  cost_micros: microsSchema.optional().nullable(),
  answer_id: z.string().optional().nullable(),
  supported: z.boolean().optional().nullable(),
});

export const loginAnswerSchema = z.object({
  island: z.string().min(1).nullable(),
  token: z.string().min(1),
  role: z.string().optional().nullable(),
});

export const gradeCriterionSchema = z.object({
  criterion: z.string(),
  weight: z.number(),
  score: z.number(),
  measured: z.boolean(),
  evidence: z.string(),
});

export const gradeSchema = z.object({
  letter: z.string(),
  score: z.number(),
  criteria: z.array(gradeCriterionSchema),
  caps: z.array(
    z.object({
      ceiling: z.string(),
      reason: z.string(),
    }),
  ),
  rule: z.string(),
});

export const briefClaimSchema = z.object({
  text: z.string(),
  paper_id: z.string(),
  paper_title: z.string(),
  agent: z.string(),
  island_id: z.string(),
  reading_id: z.string(),
  depends_on_paper: z.boolean(),
  stance: z
    .union([z.literal("positive"), z.literal("neutral"), z.literal("negative")])
    .optional()
    .nullable(),
  verified: z.boolean(),
  quote: z.string().optional().nullable(),
  created_at: z.number(),
});

export const briefPaperSchema = z.object({
  id: z.string(),
  title: z.string(),
  primary_category: z.string(),
  text_status: z.string(),
  first_seen_at: z.number(),
  islands: z.array(z.string()),
  readings: z.number().int().nonnegative(),
  runs: z.number().int().nonnegative(),
  days_left: z.number().optional().nullable(),
  let_go_after: z.iso.datetime().optional().nullable(),
  thesis: z.string().optional().nullable(),
  takeaways: z.array(z.string()).optional().nullable(),
  href: z.string().optional().nullable(),
  held: z.boolean().optional().nullable(),
  kept_by: z.array(z.string()).optional(),
});

export const briefAgentSchema = z.object({
  address: z.string(),
  island_id: z.string(),
  version: z.number().int().nonnegative(),
  generation: z.number().int().nonnegative(),
  runs: z.number().int().nonnegative(),
  completed: z.number().int().nonnegative(),
  failed: z.number().int().nonnegative(),
  reading_now: z
    .object({
      run_id: z.string(),
      paper_id: z.string(),
      paper_title: z.string(),
    })
    .optional()
    .nullable(),
});

export const briefNumbersSchema = z.record(
  z.string(),
  z.union([
    z.number(),
    z.array(
      z.object({
        reason: z.string(),
        n: z.number(),
      }),
    ),
  ]),
);

export const briefIslandSchema = z.object({
  id: z.string(),
  name: z.string(),
  focus: z.string(),
  agents: z.number().int().nonnegative(),
  evolve: z.boolean(),
  paused: z.boolean(),
  numbers: briefNumbersSchema,
});

export const briefGenerationSchema = z.object({
  island_id: z.string(),
  generation: z.number().int().nonnegative(),
  status: z.string(),
  reason: z.string().optional().nullable(),
  decisions: z.array(
    z.object({
      genome_id: z.string().optional(),
      decision: z.string().optional(),
      reason: z.string().optional(),
      usefulness: z.number().optional(),
    }),
  ),
  created_at: z.number(),
});

export const briefSchema = z.object({
  generated_at: z.number(),
  about: z.string().optional(),
  grade: gradeSchema.optional(),
  findings: z.array(z.string()).optional(),
  numbers: briefNumbersSchema.optional(),
  islands: z.array(briefIslandSchema).optional(),
  agents: z.array(briefAgentSchema).optional(),
  claims: z.array(briefClaimSchema).optional(),
  papers: z
    .object({
      held: z.number().int().nonnegative(),
      waiting: z.number().int().nonnegative(),
      released: z.number().int().nonnegative().optional(),
      let_go_after_days: z.number().int().nonnegative(),
      rule: z.string(),
      held_papers: z.array(briefPaperSchema),
      waiting_papers: z.array(briefPaperSchema),
      recent_papers: z.array(briefPaperSchema).optional(),
    })
    .optional(),
  evolution: z.array(briefGenerationSchema).optional(),
  limits: z.array(z.string()).optional(),
});

export const activityStepSchema = z.object({
  id: z.number(),
  run_id: z.string(),
  agent: z.string(),
  island_id: z.string(),
  paper_id: z.string(),
  kind: z.string(),
  tool: z.string().optional().nullable(),
  passage_id: z.string().optional().nullable(),
  looked_at: z.array(z.string()),
  created_at: z.number().int().nonnegative(),
});

export const activityPaperSchema = z.object({
  id: z.string(),
  title: z.string(),
  primary_category: z.string(),
  islands: z.array(z.string()),
});

export const activitySchema = z.object({
  steps: z.array(activityStepSchema),
  papers: z.record(z.string(), activityPaperSchema),
  last_id: z.number().int().nonnegative(),
});

export const sessionSchema = z.object({
  island: z.string().min(1),
  token: z.string().min(1),
});
export const errorSchema = z.object({
  detail: z.string(),
  code: z.string().optional(),
  field: z.string().nullable().optional(),
});
export const loginRequestSchema = z.object({
  island: z.string().min(1),
  password: z.string(),
});
export const chatRequestSchema = z.object({ message: z.string().min(1) });
export const settingsRequestSchema = z
  .object({
    evolution_enabled: z.boolean().optional(),
    mutation_enabled: z.boolean().optional(),
  })
  .refine(
    (value) =>
      (value.evolution_enabled !== undefined) !==
      (value.mutation_enabled !== undefined),
  );
export const genomeRequestSchema = z.object({
  island_id: z.string(),
  parent_id: z.string(),
  prompt: z.string(),
  tools: z.string(),
});
export const agentEditRequestSchema = z.object({
  fields: z.object({ active: z.boolean() }),
});
export const selectionRequestSchema = z.object({
  note: z.string().max(500).optional(),
});
export const likeRequestSchema = z.object({
  target_kind: z.enum([
    "paper",
    "reading",
    "agent",
    "claim",
    "idea",
    "run",
  ]),
  target_id: z.string(),
});
export const likeAnswerSchema = z.object({
  like: z.object({ liked: z.boolean(), count: z.number().int().nonnegative() }),
});
export const selectionAnswerSchema = z.object({
  paper_id: z.string(),
  held: z.boolean(),
  selected: z.boolean(),
});
export const revisionAnswerSchema = z.object({
  revision: z.number().int(),
  actor: z.string(),
  note: z.string(),
  restored_from: z.number().int().nullable(),
  changes: z.array(
    z.object({
      kind: z.string(),
      id: z.string(),
      island_id: z.string().nullable(),
      created: z.boolean(),
      fields: z.array(z.string()),
    }),
  ),
  created_at: z.number(),
  applied: z.boolean(),
  spec: z.record(z.string(), z.unknown()),
});
export const publicPaperSchema = z.object({
  thesis: z.string().nullish(),
  takeaways: z.array(z.object({ text: z.string() })).nullish(),
  used: z.number().nullish(),
});
