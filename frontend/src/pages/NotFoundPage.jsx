import { ArrowLeft } from 'lucide-react'

import Button from '../components/ui/Button'
import PageContainer from '../layouts/PageContainer'

export default function NotFoundPage() {
  return (
    <PageContainer size="narrow" className="py-24">
      <p className="font-mono text-sm text-ink-subtle">404</p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink">Page not found</h1>
      <p className="mt-2 text-ink-muted">The address you opened does not match any SakshamPay page.</p>
      <Button to="/" variant="ghost" leadingIcon={ArrowLeft} className="-ml-4 mt-8">
        Back to home
      </Button>
    </PageContainer>
  )
}
