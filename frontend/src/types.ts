export type RunStatus = 'pending' | 'running' | 'success' | 'failed' | 'skipped'
export type TriggerType = 'scheduled' | 'manual'

export interface RunSummary {
  id: number
  target_id: number
  status: RunStatus
  trigger: TriggerType
  capture_date: string
  started_at: string
  finished_at: string | null
  duration_ms: number | null
  attempts: number
  error_message: string | null
  skipped_reason: string | null
  changed: boolean | null
  change_ratio: number | null
}

export interface RunLog {
  id: number
  ts: string
  level: string
  step: string
  message: string
  attempt: number | null
}

export interface Run extends RunSummary {
  screenshot_path: string | null
  screenshot_bytes: number | null
  content_sha256: string | null
  page_title: string | null
  final_url: string | null
  drive_status: 'local' | 'pending' | 'uploaded' | 'failed'
  drive_attempts: number
  drive_last_error: string | null
  drive_uploaded_at: string | null
  drive_next_retry_at: string | null
  drive_file_link: string | null
  previous_run_id: number | null
  logs: RunLog[]
}

export interface Target {
  id: number
  name: string
  url: string
  enabled: boolean
  run_time: string | null
  cron_expression: string | null
  timezone_name: string | null
  viewport_width: number | null
  viewport_height: number | null
  full_page: boolean
  wait_until: string
  wait_after_load_ms: number | null
  timeout_ms: number | null
  user_agent: string | null
  locale: string | null
  hide_selectors: string | null
  dismiss_selectors: string | null
  session_profile: string | null
  account_id: number | null
  expected_selector: string | null
  fail_if_url_contains: string | null
  subfolder: string | null
  created_at: string
  updated_at: string
  next_run_at: string | null
  last_run: RunSummary | null
  has_session: boolean
  session_expires_at: string | null
}

export type TargetInput = Partial<Omit<Target, 'id' | 'created_at' | 'updated_at' | 'next_run_at' | 'last_run' | 'has_session' | 'session_expires_at'>>

export interface MetricPoint {
  date: string
  [key: string]: string | number
}

export interface MetricsSeries {
  keys: string[]
  points: MetricPoint[]
  labels: Record<string, string>
}

export interface Health {
  status: string
  version: string
  timezone: string
  output_dir: string
  scheduler_running: boolean
  jobs: number
  targets_enabled: number
  queue_backend: 'inline' | 'redis'
  redis_ok: boolean
  worker_alive: boolean
  queue_depth: number
  database_backend: string
  storage_backend: 'local' | 'google_drive' | 's3'
  drive_configured: boolean
}

export interface DriveCheck {
  configured: boolean
  writable: boolean
  parent_name: string | null
  shared_drive: boolean
  detail: string
}

export interface DriveRetry {
  run_id: number
  drive_status: string
  drive_file_link: string | null
  detail: string
}

export interface Job {
  job_id: string
  target_id: number
  target_name: string
  next_run_at: string | null
  trigger: string
}

export interface User {
  id: number
  email: string
  must_change_password: boolean
  last_login_at: string | null
}

export type MembershipRole = 'owner' | 'admin' | 'member' | 'viewer'

export interface Organization {
  id: number
  name: string
  slug: string
  role: MembershipRole
  created_at: string
  quota_accounts: number
  quota_targets: number
  quota_daily_captures: number
  quota_storage_bytes: number
  retention_days: number
}

export interface QuotaMetric {
  used: number
  limit: number
  remaining: number | null
  percent: number | null
  unlimited: boolean
}

export interface OrganizationUsage {
  organization_id: number
  billing_date: string
  accounts: QuotaMetric
  targets: QuotaMetric
  daily_captures: QuotaMetric
  storage_bytes: QuotaMetric
  retention_days: number
}

export interface OrganizationMember {
  membership_id: number
  user_id: number
  email: string
  role: MembershipRole
  created_at: string
}

export interface OrganizationInvitation {
  id: number
  email: string
  role: MembershipRole
  created_at: string
  expires_at: string
  accepted_at: string | null
  revoked_at: string | null
  delivery: 'sent' | 'logged' | null
  invite_url: string | null
}

export interface InvitationPreview {
  organization_name: string
  email: string
  role: MembershipRole
  expires_at: string
  user_exists: boolean
}

export type AccountStatus =
  | 'never'
  | 'connected'
  | 'disconnected'
  | 'expired'
  | 'verification_required'
  | 'error'

export interface Account {
  id: number
  name: string
  platform: string
  status: AccountStatus
  last_verified_at: string | null
  last_success_at: string | null
  last_error: string | null
  created_at: string
  has_session: boolean
  session_expires_at: string | null
  target_count: number
}

export interface LoginStatus {
  active: boolean
  account_id: number | null
  logged_in: boolean
  current_url: string | null
  platform: string | null
  novnc_path: string | null
  detail: string | null
}

export interface SessionTest {
  account_id: number
  status: AccountStatus
  logged_in: boolean
  final_url: string | null
  detail: string
}

export interface SessionStatus {
  target_id: number
  has_session: boolean
  session_profile: string | null
  cookie_count: number
  expires_at: string | null
  expired: boolean
  detail: string
}

// Lien de lecture vers la capture distante. Sur S3 il est signe et expire :
// expire_dans_secondes indique sa duree de validite (null sur Drive).
export interface LienCapture {
  url: string | null
  expire_dans_secondes: number | null
}
