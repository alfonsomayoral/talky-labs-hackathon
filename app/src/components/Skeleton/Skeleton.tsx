import clsx from 'clsx'
import styles from './Skeleton.module.css'

export interface SkeletonProps {
  width?: number | string
  height?: number | string
  radius?: number | string
  /** Renders a paragraph of bars (last one shorter). */
  lines?: number
  className?: string
}

/** Placeholder block while data loads. Match the shape of what is coming. */
export function Skeleton({ width = '100%', height = 12, radius = 'var(--radius-xs)', lines, className }: SkeletonProps) {
  if (lines && lines > 1) {
    return (
      <span className={clsx(styles.lines, className)} aria-hidden>
        {Array.from({ length: lines }, (_, i) => (
          <span
            key={i}
            className={styles.skeleton}
            style={{ width: i === lines - 1 ? '60%' : width, height, borderRadius: radius }}
          />
        ))}
      </span>
    )
  }
  return <span className={clsx(styles.skeleton, className)} style={{ width, height, borderRadius: radius }} aria-hidden />
}
