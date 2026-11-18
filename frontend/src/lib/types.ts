export type Role = "owner" | "admin" | "analyst" | "viewer";

export interface User { id: string; email: string; full_name: string; preferences: Record<string, unknown>; last_workspace_id: string | null }
export interface WorkspaceSummary { id: string; name: string; role: Role; currency: string; onboarding: Onboarding }
export interface Onboarding { step?: number; completed?: boolean; dataset_id?: string }
export interface Me { user: User; workspaces: WorkspaceSummary[]; invitations: { id: string; workspace_name: string; role: Role }[] }

export interface Workspace {
  id: string; name: string; industry: string; business_type: string; currency: string; timezone: string;
  fiscal_year_start_month: number; date_format: string; external_ai_enabled: boolean;
  insight_settings: Record<string, number>; onboarding: Onboarding; role: Role; created_at: string;
  ai: { provider_configured: boolean; provider: string; model: string | null; active_mode: "local" | "anthropic" };
}

export interface DatasetVersion { id: string; version_number: number; row_count: number; column_count: number; note: string; created_at: string; quality_score: number | null; transformation?: { kind: string; params: Record<string, unknown> } }
export interface Dataset {
  id: string; name: string; description: string; original_filename: string; source_type: string; is_demo: boolean;
  status: "uploaded" | "needs_sheet" | "processing" | "ready" | "failed"; status_message: string; file_size: number; created_at: string;
  sheets: { name: string; rows: number; columns: number; empty: boolean }[]; sheet_name: string;
  current_version: DatasetVersion | null; row_count: number | null; column_count: number | null; quality_score: number | null;
  import_report?: Record<string, unknown>; readiness?: { ready: boolean; checks: { label: string; ok: boolean }[]; measures: number; dimensions: number; dates: number };
  version_count?: number;
}

export interface Column {
  id: string; position: number; name: string; original_name: string; display_name: string; dtype: string; semantic_type: string;
  semantic_confirmed: boolean; business_meaning: string; meaning_confidence: number; excluded: boolean; null_count: number;
  unique_count: number; invalid_count: number; examples: unknown[]; stats: Record<string, any>;
}

export interface Metric {
  id: string; key: string; name: string; description: string; formula: string; category: string; status: string; verified: boolean;
  verified_at: string | null; dataset_id: string; unit: string; decimals: number; aggregation_type: string; default_date_column: string;
  dimensions: string[]; columns_used: string[]; synonyms: string[]; version: number; version_id: string; created_at: string;
  versions?: { id: string; version: number; name: string; formula: string; unit: string; change_note: string; created_at: string }[];
  usage?: { analysis_runs: number; recent: { id: string; question: string; source: string; created_at: string; metric_version: number }[] };
  readable_formula?: string; valid?: boolean; validation_error?: string;
}

export interface ResultColumn { key: string; label: string; role: string; unit?: string; decimals?: number }
export interface Kpi { key: string; label: string; value: number | null; unit?: string; decimals?: number; text?: string }
export interface Provenance {
  dataset: { id: string; name: string; version_id: string; version_number: number; total_rows: number; is_demo: boolean };
  records_in_scope: number; filters: string[]; time_column: string | null; date_range: string; grouping: string[];
  measures: { label: string; definition: string; unit: string; aggregation_type: string; source: string }[];
  metrics: { metric_id: string; metric_version_id: string; version: number; name: string; formula: string; readable: string; verified: boolean }[];
  methodology: string; queries: { purpose: string; sql: string; params: unknown[]; duration_ms: number }[];
  engine: string; duration_ms: number; executed_at: string; cache_hit: boolean;
}
export interface AnalysisResult {
  intent: string; columns: ResultColumn[]; rows: Record<string, any>[]; kpis?: Kpi[]; chart?: { type: string; x?: string; y?: string[]; series?: string | null };
  notes: string[]; provenance: Provenance; totals?: Record<string, any>; total_groups?: number; truncated?: boolean; empty?: boolean;
  periods?: { current: { start: string; end: string; label: string }; baseline: { start: string; end: string; label: string }; grain: string };
  grain?: string; series?: string[]; method?: string; level?: string; bounds?: { low: number; high: number; median: number }; stats?: Record<string, number>;
}
export interface Run { id: string; dataset_id: string; dataset_version_id: string; plan: Plan; plan_notes: string[]; interpreter: string; question: string; status: string; result: AnalysisResult; created_at: string; source: string }

export interface Filter { column: string; op: string; value?: unknown }
export interface MeasureRef { kind: "metric" | "column" | "count_rows"; metric_id?: string | null; column?: string | null; aggregation?: string | null }
export interface Plan {
  intent: string; dataset_id: string; measures: MeasureRef[]; group_by: string[]; filters: Filter[];
  time?: { column: string; grain?: string | null; start?: string | null; end?: string | null } | null;
  comparison?: { mode: string; grain: string; current?: { start: string; end: string } | null; baseline?: { start: string; end: string } | null } | null;
  focus?: { column: string; values: string[] } | null; sort?: { by: string; direction: string }; limit?: number; visualization?: string;
  options?: Record<string, unknown>;
}

export interface Message {
  id: string; seq: number; role: "user" | "assistant"; content: string; kind: string; pinned: boolean; note: string; created_at: string;
  payload: {
    answer?: string; observations?: string[]; follow_ups?: string[]; notes?: string[]; mode?: string; interpreter?: string;
    ai_explanation?: string | null; clarification?: { question: string; kind: string; options: { label: string; description?: string }[] };
    answered?: number; suggestions?: string[]; problems?: string[]; dataset_version?: number; dataset_version_id?: string;
    describe?: { columns: { name: string; type: string; role: string; meaning: string }[]; metrics: string[]; unavailable: { metric: string; reason: string }[] };
  };
  run: Run | null;
}
export interface Conversation {
  id: string; title: string; saved: boolean; dataset_id: string | null; dataset_name: string | null; notes: string; findings: string[];
  created_at: string; updated_at: string; message_count: number; pinned_count: number; messages?: Message[]; dataset_current_version_id?: string;
}

export interface Insight {
  id: string; dataset_id: string; category: string; category_label: string; severity: "high" | "medium" | "low"; score: number; title: string;
  finding: string; metric: string; baseline: string; date_range: string; method: string; limitations: string; calculations: Record<string, any>;
  evidence_plan: Plan | null; suggested_question: string; status: "new" | "saved" | "dismissed"; note: string; created_at: string;
}

export interface ReportSection { id: string; position: number; kind: string; title: string; body: string; plan: Plan | null; snapshot: Record<string, any>; source_ref: string; created_at: string }
export interface Report {
  id: string; title: string; subtitle: string; dataset_id: string | null; dataset_name: string | null; is_demo: boolean; dataset_version: number | null;
  period_start: string; period_end: string; period_label: string; status: "draft" | "final"; created_at: string; updated_at: string;
  section_count: number; sections?: ReportSection[];
}
