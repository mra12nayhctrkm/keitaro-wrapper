interface Props {
  values: number[]
  label: string
  width?: number
  height?: number
}

/** Tiny inline chart of a daily series (no chart library needed). */
export function Sparkline({ values, label, width = 96, height = 24 }: Props) {
  if (values.length === 0) return null
  const max = Math.max(...values, 1)
  const step = values.length > 1 ? width / (values.length - 1) : 0
  const points = values
    .map((v, i) => `${(i * step).toFixed(1)},${(height - 2 - (v / max) * (height - 4)).toFixed(1)}`)
    .join(' ')
  return (
    <svg className="sparkline" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label}: ${values.join(', ')}`}>
      {values.length > 1 ? (
        <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" />
      ) : (
        <circle cx={width / 2} cy={height / 2} r="2" fill="currentColor" />
      )}
    </svg>
  )
}
