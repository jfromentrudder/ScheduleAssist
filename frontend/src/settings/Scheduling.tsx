/** The preferences the generator reads (#15).
 *
 * Everything here changes what a generated schedule looks like, so saving any
 * of it tells the caller the current schedule is stale and should be rebuilt. */

import { useState } from 'react'

export type SchedulingPrefs = {
  workdays: number[]
  /** "HH:MM:SS" */
  day_start: string
  day_end: string
  period_minutes: number
  lunch_minutes: number
  timezone: string
  schedule_horizon_days: number
  schedule_horizon_warning: string | null
}

// Mirrors the constants in backend/app/scheduler.py, which are also the
// bounds of the CHECK constraints on the column.
const MIN_HORIZON_DAYS = 1
const MAX_HORIZON_DAYS = 21
const MIN_PERIOD_MINUTES = 15
const MAX_PERIOD_MINUTES = 240
const MIN_LUNCH_MINUTES = 30
const MAX_LUNCH_MINUTES = 120

/** Monday first, matching `date.weekday()` where Monday is 0. */
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const PERIOD_CHOICES = [25, 30, 45, 50, 60, 90]
const LUNCH_CHOICES = [30, 45, 60, 90, 120]

/** Every zone the browser knows, so the list matches the user's own machine. */
function timezones(): string[] {
  const supported = (
    Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
  ).supportedValuesOf
  try {
    if (supported) return supported('timeZone')
  } catch {
    // Older browsers: fall through to the guessed zone alone.
  }
  return [Intl.DateTimeFormat().resolvedOptions().timeZone, 'UTC']
}

/** "HH:MM:SS" from the API to the "HH:MM" a time input wants. */
function toTimeInput(value: string): string {
  return value.slice(0, 5)
}

type Props = {
  prefs: SchedulingPrefs
  onSave: (change: Partial<SchedulingPrefs>) => Promise<void>
  busy: boolean
}

export function Scheduling({ prefs, onSave, busy }: Props) {
  const [zones] = useState(timezones)
  const detected = Intl.DateTimeFormat().resolvedOptions().timeZone

  const toggleDay = (day: number) => {
    const next = prefs.workdays.includes(day)
      ? prefs.workdays.filter((d) => d !== day)
      : [...prefs.workdays, day]
    void onSave({ workdays: next.sort((a, b) => a - b) })
  }

  return (
    <section>
      <h3>Scheduling</h3>

      <div className="field">
        <label id="workdays-label">Workdays</label>
        <p className="field-hint">
          Days ScheduleAssist may put work periods on.
        </p>
        <div className="choices" role="group" aria-labelledby="workdays-label">
          {DAYS.map((label, day) => (
            <button
              key={label}
              type="button"
              className="choice"
              aria-pressed={prefs.workdays.includes(day)}
              disabled={busy}
              onClick={() => toggleDay(day)}
            >
              {label}
            </button>
          ))}
        </div>
        {prefs.workdays.length === 0 && (
          <p className="field-warning" role="status">
            With no workdays selected, nothing can be scheduled.
          </p>
        )}
      </div>

      <div className="field">
        <label>Working hours</label>
        <p className="field-hint">
          The earliest and latest a period may be placed on a workday.
        </p>
        <div className="window-picker">
          <label>
            From
            <input
              type="time"
              value={toTimeInput(prefs.day_start)}
              disabled={busy}
              onChange={(e) =>
                void onSave({ day_start: `${e.target.value}:00` })
              }
            />
          </label>
          <label>
            To
            <input
              type="time"
              value={toTimeInput(prefs.day_end)}
              disabled={busy}
              onChange={(e) => void onSave({ day_end: `${e.target.value}:00` })}
            />
          </label>
        </div>
      </div>

      <div className="field">
        <label htmlFor="period-len">Period length</label>
        <p className="field-hint">
          How long one block of work is. Anything shorter than this is left
          empty rather than part-filled.
        </p>
        <select
          id="period-len"
          className="calendar-kind"
          value={prefs.period_minutes}
          disabled={busy}
          onChange={(e) =>
            void onSave({ period_minutes: Number(e.target.value) })
          }
        >
          {PERIOD_CHOICES.filter(
            (m) => m >= MIN_PERIOD_MINUTES && m <= MAX_PERIOD_MINUTES,
          ).map((minutes) => (
            <option key={minutes} value={minutes}>
              {minutes} minutes
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label htmlFor="lunch-len">Meal break</label>
        <p className="field-hint">
          Kept clear in the middle of a working day. ScheduleAssist takes as
          much of this as it can, and never less than {MIN_LUNCH_MINUTES}{' '}
          minutes.
        </p>
        <select
          id="lunch-len"
          className="calendar-kind"
          value={prefs.lunch_minutes}
          disabled={busy}
          onChange={(e) =>
            void onSave({ lunch_minutes: Number(e.target.value) })
          }
        >
          {LUNCH_CHOICES.filter(
            (m) => m >= MIN_LUNCH_MINUTES && m <= MAX_LUNCH_MINUTES,
          ).map((minutes) => (
            <option key={minutes} value={minutes}>
              {minutes} minutes
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label htmlFor="tz">Timezone</label>
        <p className="field-hint">
          Working hours are wall-clock times, so they need a zone to mean
          anything.
        </p>
        <select
          id="tz"
          className="calendar-kind"
          value={prefs.timezone}
          disabled={busy}
          onChange={(e) => void onSave({ timezone: e.target.value })}
        >
          {zones.map((zone) => (
            <option key={zone} value={zone}>
              {zone}
            </option>
          ))}
        </select>
        {prefs.timezone !== detected && (
          <p className="field-hint">
            This device is in {detected}.{' '}
            <button
              className="text-button"
              disabled={busy}
              onClick={() => void onSave({ timezone: detected })}
            >
              Use that instead
            </button>
          </p>
        )}
      </div>

      <div className="field">
        <label htmlFor="horizon">Planning horizon</label>
        <p className="field-hint">
          How far ahead your schedule is settled. Work periods inside the
          horizon stay put when new events arrive; beyond it they are
          rearranged to fit.
        </p>
        <div className="slider-row">
          <input
            id="horizon"
            type="range"
            min={MIN_HORIZON_DAYS}
            max={MAX_HORIZON_DAYS}
            value={prefs.schedule_horizon_days}
            disabled={busy}
            onChange={(e) =>
              void onSave({ schedule_horizon_days: Number(e.target.value) })
            }
            aria-describedby="horizon-value"
          />
          <output id="horizon-value" htmlFor="horizon">
            {prefs.schedule_horizon_days}
            {prefs.schedule_horizon_days === 1 ? ' day' : ' days'}
          </output>
        </div>
        {prefs.schedule_horizon_warning && (
          <p className="field-warning" role="status">
            {prefs.schedule_horizon_warning}
          </p>
        )}
      </div>
    </section>
  )
}
