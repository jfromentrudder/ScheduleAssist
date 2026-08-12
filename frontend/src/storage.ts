/** localStorage that cannot throw.
 *
 * Private browsing and blocked third-party storage both raise on access, and a
 * preference failing to persist is never worth breaking a render over. Every
 * read is guarded rather than cast, so a value edited by hand — or left behind
 * by an older version of the app — falls back instead of poisoning state. */

export function readStored<T>(
  key: string,
  guard: (value: unknown) => value is T,
  fallback: T,
): T {
  try {
    const stored = localStorage.getItem(key)
    return guard(stored) ? stored : fallback
  } catch {
    return fallback
  }
}

export function store(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // The preference still applies for this session; it just won't persist.
  }
}
