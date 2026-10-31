/** SakshamPay wordmark: a line-drawn shield with a check, plus the product name. */
export default function Logo({ className = '' }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <svg viewBox="0 0 32 32" fill="none" aria-hidden="true" className="size-7">
        <rect width="32" height="32" rx="7" className="fill-ink" />
        <path
          d="M16 6.5 8.5 9.5v6c0 4.6 3.1 8.4 7.5 9.9 4.4-1.5 7.5-5.3 7.5-9.9v-6L16 6.5Z"
          className="stroke-surface"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
        <path
          d="m12.5 16 2.4 2.4 4.6-4.8"
          className="stroke-surface"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className="text-[17px] font-semibold tracking-tight text-ink">SakshamPay</span>
    </span>
  )
}
