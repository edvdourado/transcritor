// mm:ss below one hour, h:mm:ss thereafter. Never round elapsed time up.
export function formatDuration(seconds: number): string {
  const whole = Math.floor(Math.max(0, Number.isFinite(seconds) ? seconds : 0))
  const minutes = Math.floor(whole / 60)
  const tail = `${String(minutes % 60).padStart(2, '0')}:${String(whole % 60).padStart(2, '0')}`
  return whole >= 3600 ? `${Math.floor(whole / 3600)}:${tail}` : tail
}
