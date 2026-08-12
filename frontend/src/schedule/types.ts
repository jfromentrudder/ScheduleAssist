export type EventType = 'deadline' | 'one_time'
export type EventSource = 'imported' | 'manual'

/** What an event's time means for generation.
 *
 * - `busy` — occupied; periods are scheduled around it.
 * - `free` — informational; neither blocks time nor offers any.
 * - `work_window` — time available for work; periods are placed *inside* it. */
export type Availability = 'busy' | 'free' | 'work_window' | 'meal'

/** Generated blocks are either allocated work or a break held clear. */
export type PeriodKind = 'work' | 'meal'

/** `generated` is the app's own output; `calendar` is the raw diary. */
export type ScheduleView = 'generated' | 'calendar'

/** How much time is on screen at once. Independent of `ScheduleView`: either
 *  view can be read a day, a week or a month at a time. */
export type ScheduleSpan = 'day' | 'week' | 'month'

export function isScheduleSpan(value: unknown): value is ScheduleSpan {
  return value === 'day' || value === 'week' || value === 'month'
}

export type ScheduleEvent = {
  id: number
  title: string
  description: string | null
  event_type: EventType
  source: EventSource
  availability: Availability
  /** Set for one_time events; null for deadlines. */
  starts_at: string | null
  ends_at: string | null
  /** Set for deadlines; null for one_time events. */
  due_at: string | null
  is_all_day: boolean
  expected_prep_minutes: number | null
  /** The user has corrected this, so syncing will not reclassify it. */
  type_locked: boolean
}

export type SchedulePeriod = {
  id: number
  starts_at: string
  ends_at: string
  kind: PeriodKind
  /** Inside the commitment horizon, so regeneration will not move it. */
  locked: boolean
  /** The events this block was generated to serve. Empty for a meal. */
  events: { id: number; title: string }[]
}

export type Preferences = {
  workdays: number[]
  /** "HH:MM:SS" */
  day_start: string
  day_end: string
  period_minutes: number
  timezone: string
  /** Days ahead, counting today, that the schedule is treated as settled. */
  schedule_horizon_days: number
}

export type Schedule = {
  start: string
  end: string
  view: ScheduleView
  preferences: Preferences
  /** Local midnight where the settled part of the schedule ends.
   *  Null in the calendar view, which carries no periods to settle. */
  horizon_ends_at: string | null
  events: ScheduleEvent[]
  periods: SchedulePeriod[]
}

/** How a block is rendered — the categories the view must distinguish. */
export type BlockKind = 'imported' | 'manual' | 'period' | 'meal'
