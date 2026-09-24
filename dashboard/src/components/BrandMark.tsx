export function BrandMark({ className = 'brand-mark' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 44 40" role="img" aria-label="Nina">
      <path fill="#FFCE3A" d="M3 4a3 3 0 0 1 3-3h23.5c1.2 0 2.3.5 3.1 1.4l9.7 15a3 3 0 0 1 0 3.2l-9.7 15a3 3 0 0 1-2.6 1.4H6a3 3 0 0 1-3-3V4Z" />
      <circle cx="32.5" cy="19" r="3" fill="#1C2340" />
      <path fill="#1C2340" d="M10 28V10h4.2l7 10.8V10H26v18h-4.1l-7.1-10.9V28H10Z" />
    </svg>
  )
}
