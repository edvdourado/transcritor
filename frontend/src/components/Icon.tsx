import type { CSSProperties } from 'react'

const paths = {
  wave: 'M3 10v4m4-7v10m5-14v18m5-14v10m4-7v4',
  upload: 'M12 16V3m-5 5 5-5 5 5M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4',
  arrow: 'M4 12h16m-6-6 6 6-6 6',
  file: 'M14 2H5v20h14V7l-5-5Zm0 0v6h5M8 13h8m-8 4h5',
  check: 'm5 12 4 4L19 6',
  close: 'm6 6 12 12M6 18 18 6',
  copy: 'M9 9h12v12H9zM15 5V3H3v12h2',
  download: 'M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4',
  sun: 'M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1 1m12 12 1 1M5 19l1-1M18 6l1-1M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
  moon: 'M20 15.5A9 9 0 0 1 8.5 4 9 9 0 1 0 20 15.5Z',
  audio: 'M9 18V5l11-2v13M9 14c-6-2-7 6-2 6 2 0 2-2 2-2m11-6c-6-2-7 6-2 6 2 0 2-2 2-2',
} as const

export function Icon({ name, size = 20, style }: { name: keyof typeof paths; size?: number; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}><path d={paths[name]} /></svg>
}
