// Talky's logo mark (pink blob with an orange outline), traced from the brand logo. Same shape as public/favicon.svg.
const PATH =
  'M22.2 14.07C22.32 16.16 22.38 16.15 21.18 17.26C19.99 18.37 16.97 20.03 15.02 20.74C13.08 21.44 11.18 21.94 9.5 21.47C7.82 20.99 6.24 19.4 4.97 17.9C3.69 16.39 1.93 13.98 1.84 12.42C1.75 10.85 3.02 9.7 4.41 8.51C5.81 7.31 8.18 6.26 10.18 5.24C12.19 4.21 14.74 2.44 16.45 2.36C18.16 2.28 19.49 2.81 20.45 4.76C21.41 6.71 22.07 11.99 22.2 14.07Z'

export interface TalkyMarkProps {
  /** Width and height in px. */
  size?: number
  /** Accessible name; omit when text next to the mark already names it. */
  title?: string
  className?: string
}

export function TalkyMark({ size = 22, title, className }: TalkyMarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      className={className}
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      {title && <title>{title}</title>}
      <path d={PATH} fill="#FEDDE4" stroke="#F97447" strokeWidth={1.3} strokeLinejoin="round" />
    </svg>
  )
}
