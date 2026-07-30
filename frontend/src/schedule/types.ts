export type EventType = 'deadline' | 'one_time'
export type EventSource = 'imported' | 'manual'

export type ScheduleEvent = {
  id: number
  title: string
  description: string | null
  event_type: EventType
  source: EventSource
  /** Set for one_time events; null for deadlines. */
  starts_at: string | null
  ends_at: string | null
  /** Set for deadlines; null for one_time events. */
  due_at: string | null
  is_all_day: boolean
  expected_prep_minutes: number | null
}

export type SchedulePeriod = {
  id: number
  starts_at: string
  ends_at: string
  /** The events this block was generated to serve. */
  events: { id: number; title: string }[]
}

export type Preferences = {
  workdays: number[]
  /** "HH:MM:SS" */
  day_start: string
  day_end: string
  period_minutes: number
  timezone: string
}

export type Schedule = {
  start: string
  end: string
  preferences: Preferences
  events: ScheduleEvent[]
  periods: SchedulePeriod[]
}

/** How a block is rendered — the three categories the view must distinguish. */
export type BlockKind = 'imported' | 'manual' | 'period'
