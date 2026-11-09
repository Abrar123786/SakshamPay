import { Card, CardBody } from '../../components/ui/Card'
import PageContainer from '../../layouts/PageContainer'
import PageHeader from '../../layouts/PageHeader'

/** Shared frame for the sign-in and registration pages: title, form card, switch link. */
export default function AuthPageLayout({ title, description, footer, children }) {
  return (
    <PageContainer size="narrow" className="py-10 sm:py-16">
      <title>{`${title} · SakshamPay`}</title>
      <div className="mx-auto max-w-md">
        <PageHeader title={title} description={description} />
        <Card as="div" className="mt-8">
          <CardBody>{children}</CardBody>
        </Card>
        {footer && <p className="mt-6 text-center text-sm text-ink-muted">{footer}</p>}
      </div>
    </PageContainer>
  )
}
