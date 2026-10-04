export type Skill = "bylaw" | "roads";
export type LonLat = [number, number];

export interface Crew {
  id: string;
  skill: Skill;
  depot_lat: number;
  depot_lon: number;
  shift_min: number;
  capacity: number;
}

export interface LiveRoute {
  crew: string;
  skill: Skill;
  stops: string[];
  path: LonLat[];
  geometry?: LonLat[] | null;
  minutes: number | null;
  km: number | null;
}

export interface LiveJob {
  job_id: string;
  skill: Skill;
  service_name: string;
  comm_code: string | null;
  lat: number;
  lon: number;
  n_tickets: number;
  priority: number;
  exposure: number;
  report_count: number;
  reason: string | null;
  crew: string | null;
  eta_min: number | null;
}

export interface LivePlan {
  day: string;
  crews: Crew[];
  routes: LiveRoute[];
  km: number;
  jobs: LiveJob[];
  voice_jobs: string[];
}

export interface LiveMetrics {
  live: {
    day: string;
    open_tickets: number;
    tickets_planned_today: number;
    km: number;
    high_risk_planned: number;
    voice_tickets: number;
    crews_active: number;
  };
}

export interface DisruptionResult {
  jobs_moved: number;
  replan_s: number;
  high_risk_planned_before: number;
  high_risk_planned_after: number;
  high_risk_open: number;
  high_risk_coverage: number;
  crews_out?: string[];
  crews_active?: number;
  new_tickets?: number;
  surge_date?: string;
}

export type PolicyKey = "fifo" | "optimized" | "optimized_disruption";

export interface PolicyMetrics {
  high_risk_within_48h: number;
  all_within_48h: number;
  high_risk_served: number;
  low_risk_served: number;
  p90_days_to_service: number;
  p90_days_high_risk: number;
  median_days_to_service: number;
  tickets_served: number;
  backlog_end: number;
  total_km: number;
  km_per_ticket: number;
  stops: number;
  stops_consolidated?: number;
  jobs_moved_per_replan?: number | null;
  replan_s_max?: number | null;
}

export interface Replan {
  kind: string;
  day: string;
  jobs_moved: number;
  jobs_before: number;
  high_risk_planned_before: number;
  high_risk_planned_after: number;
  replan_s: number;
  crews_out?: string[];
  n_new?: number;
}

export interface DayInfo {
  day: string;
  open_morning: number;
  arrivals: number;
  served: number;
  km: number;
  stops: number;
  solve_s: number;
  high_risk_served: number;
  crews_active: number;
}

export interface ReplayRoute {
  crew: string;
  skill: Skill;
  path: LonLat[];
  geometry?: LonLat[] | null;
  stops: number;
  km: number;
  minutes: number;
}

export interface ReplayMarker {
  comm_code: string;
  skill: Skill;
  lat: number;
  lon: number;
  open: number;
  served_today: number;
  exposure: number;
  high_risk: number;
  reason: string | null;
  name: string | null;
}

export interface ReplayDay {
  info: DayInfo;
  routes: ReplayRoute[];
  markers: ReplayMarker[];
}

export interface ReplaySummary {
  days: string[];
  capacity: Record<Skill, { crews: number; tickets_per_crew: number; daily_capacity: number; median_daily_closures: number }>;
  crews: Crew[];
  policies: Record<PolicyKey, { metrics: PolicyMetrics; replans: Replan[]; daily: DayInfo[] }>;
  generated_mtime: string;
}

export interface ResultsFile {
  days: string[];
  capacity: ReplaySummary["capacity"];
  crews: Crew[];
  policies: Record<PolicyKey, { metrics: PolicyMetrics; replans: Replan[]; daily: ReplayDay[] }>;
}
