import { ArrowRight, BadgeCheck, Plus, Search, Trash2, UserPlus, X } from 'lucide-react'
import { useState } from 'react'

import {
  Badge,
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  ErrorState,
  Field,
  IconButton,
  InlineAlert,
  Input,
  LoadingState,
  RiskBadge,
  Skeleton,
} from '../../components/ui'
import PageContainer from '../../layouts/PageContainer'
import PageHeader from '../../layouts/PageHeader'
import { formatINR } from '../../utils/format'

/*
 * Development-only gallery (/__ui) of every UI primitive and state, used for visual
 * review and accessibility checks. Never registered in production builds (see routes.jsx).
 */

const COLOUR_TOKENS = [
  ['ink', 'bg-ink', 'Primary text'],
  ['ink-muted', 'bg-ink-muted', 'Secondary text'],
  ['ink-subtle', 'bg-ink-subtle', 'Captions, placeholders'],
  ['surface', 'bg-surface', 'Page background'],
  ['surface-raised', 'bg-surface-raised', 'Cards, inputs'],
  ['surface-muted', 'bg-surface-muted', 'Hover, table headers'],
  ['line', 'bg-line', 'Decorative borders'],
  ['line-input', 'bg-line-input', 'Form-control outlines'],
  ['brand', 'bg-brand', 'Primary actions, links'],
  ['brand-soft', 'bg-brand-soft', 'Info and success backgrounds'],
  ['danger', 'bg-danger', 'Errors, destructive actions'],
  ['danger-soft', 'bg-danger-soft', 'Error backgrounds'],
]

const TYPE_SCALE = [
  ['text-4xl', 'H1 · 36/40 · 600', 'text-4xl font-semibold tracking-tight'],
  ['text-3xl', 'H2 · 30/36 · 600', 'text-3xl font-semibold tracking-tight'],
  ['text-2xl', 'H3 · 24/32 · 600', 'text-2xl font-semibold tracking-tight'],
  ['text-xl', 'H4 · 20/28 · 600', 'text-xl font-semibold'],
  ['text-lg', 'Lead · 18/28', 'text-lg'],
  ['text-base', 'Body · 16/24', 'text-base'],
  ['text-sm', 'Small, labels · 14/20', 'text-sm'],
  ['text-xs', 'Caption · 12/16', 'text-xs'],
]

function Section({ id, title, children }) {
  return (
    <section aria-labelledby={id} className="space-y-4 border-t border-line pt-8">
      <h2 id={id} className="text-xl font-semibold text-ink">
        {title}
      </h2>
      {children}
    </section>
  )
}

function Row({ label, children }) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-6">
      <p className="w-32 shrink-0 text-sm text-ink-subtle">{label}</p>
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </div>
  )
}

export default function UiGalleryPage() {
  const [email, setEmail] = useState('asha.rao@example')
  const [saving, setSaving] = useState(false)
  const emailError = email.includes('.') && email.split('@')[1]?.includes('.') ? undefined : 'Enter a valid email address.'

  const save = () => {
    setSaving(true)
    window.setTimeout(() => setSaving(false), 1500)
  }

  return (
    <PageContainer className="space-y-10 py-12">
      <PageHeader
        eyebrow="Development only"
        title="UI gallery"
        description="Every SakshamPay UI primitive and state. This page exists only in the development server."
        actions={<Badge tone="neutral">Not in production builds</Badge>}
      />

      <Section id="colours" title="Colour tokens">
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {COLOUR_TOKENS.map(([name, swatch, use]) => (
            <li key={name} className="overflow-hidden rounded-md border border-line bg-surface-raised">
              <div className={`h-10 border-b border-line ${swatch}`} />
              <div className="px-3 py-2">
                <p className="font-mono text-xs text-ink">{name}</p>
                <p className="text-xs text-ink-muted">{use}</p>
              </div>
            </li>
          ))}
        </ul>
        <p className="text-sm text-ink-muted">
          Risk colours are not listed as swatches: they appear only through RiskBadge (below).
        </p>
      </Section>

      <Section id="typography" title="Typography (IBM Plex Sans)">
        <div className="space-y-3">
          {TYPE_SCALE.map(([token, meta, classes]) => (
            <div key={token} className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-6">
              <p className="w-44 shrink-0 font-mono text-xs text-ink-subtle">
                {token} · {meta}
              </p>
              <p className={`${classes} text-ink`}>Check a payment before it leaves</p>
            </div>
          ))}
        </div>
        <div className="rounded-md border border-line bg-surface-raised p-4">
          <p className="mb-2 text-sm text-ink-muted">Amounts (formatINR, tabular digits line up):</p>
          <ul className="space-y-1 text-right text-lg text-ink sm:w-60">
            {[10_000_000, 4_800_000, 770_000, 12_345].map((paise) => (
              <li key={paise}>{formatINR(paise)}</li>
            ))}
          </ul>
        </div>
      </Section>

      <Section id="buttons" title="Buttons">
        <Row label="Variants">
          <Button>Continue</Button>
          <Button variant="secondary">Verify first</Button>
          <Button variant="ghost">View details</Button>
          <Button variant="danger" leadingIcon={Trash2}>
            Remove payee
          </Button>
        </Row>
        <Row label="Sizes">
          <Button size="sm">Small</Button>
          <Button size="md">Medium</Button>
          <Button size="lg" trailingIcon={ArrowRight}>
            Large
          </Button>
        </Row>
        <Row label="States">
          <Button loading={saving} onClick={save}>
            {saving ? 'Saving' : 'Save (try me)'}
          </Button>
          <Button disabled>Disabled</Button>
          <Button variant="secondary" to="/">
            Link styled as button
          </Button>
        </Row>
        <Row label="Icon buttons">
          <IconButton icon={X} label="Close" />
          <IconButton icon={Plus} label="Add beneficiary" variant="secondary" />
          <IconButton icon={Search} label="Search" size="sm" />
        </Row>
      </Section>

      <Section id="forms" title="Labels, inputs and fields">
        <div className="grid gap-6 md:grid-cols-2">
          <Field label="Full name" hint="As it appears on your bank account.">
            {(control) => <Input autoComplete="name" placeholder="Asha Rao" {...control} />}
          </Field>
          <Field label="Email" error={emailError}>
            {(control) => (
              <Input type="email" value={email} onChange={(event) => setEmail(event.target.value)} {...control} />
            )}
          </Field>
          <Field label="Amount" hint="Simulated payments only.">
            {(control) => <Input inputMode="decimal" prefix="₹" placeholder="0.00" size="lg" {...control} />}
          </Field>
          <Field label="Note" optional>
            {(control) => <Input placeholder="Rent for November" {...control} />}
          </Field>
          <Field label="Account reference" hint="Locked after the beneficiary is saved.">
            {(control) => <Input value="XXXXXXXX4321" disabled readOnly {...control} />}
          </Field>
        </div>
      </Section>

      <Section id="cards" title="Cards">
        <div className="grid gap-6 md:grid-cols-2">
          <Card aria-labelledby="card-demo-title">
            <CardHeader
              titleId="card-demo-title"
              title="Ravi Kumar"
              description="ra****@sakshamdemo"
              actions={
                <Badge tone="brand" icon={BadgeCheck}>
                  Verified
                </Badge>
              }
            />
            <CardBody>
              <p className="text-sm text-ink-muted">Last payment {formatINR(250_000)} on 2 November.</p>
            </CardBody>
            <CardFooter>
              <Button variant="secondary" size="sm">
                Edit
              </Button>
              <Button size="sm" leadingIcon={UserPlus}>
                Pay
              </Button>
            </CardFooter>
          </Card>
          <Card aria-labelledby="card-loading-title" aria-busy="true">
            <CardHeader titleId="card-loading-title" title="Recent activity" />
            <CardBody className="space-y-3">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-4 w-2/3" />
              <LoadingState inline label="Loading recent activity" className="pt-1" />
            </CardBody>
          </Card>
        </div>
      </Section>

      <Section id="badges" title="Badges and risk badges">
        <Row label="Badges">
          <Badge>New payee</Badge>
          <Badge tone="brand" icon={BadgeCheck}>
            Verified
          </Badge>
          <Badge tone="danger">Failed</Badge>
        </Row>
        <Row label="Risk (md)">
          <RiskBadge level="LOW" score={15} />
          <RiskBadge level="MEDIUM" score={43} />
          <RiskBadge level="HIGH" score={75} />
        </Row>
        <Row label="Risk (sm)">
          <RiskBadge level="LOW" size="sm" />
          <RiskBadge level="MEDIUM" size="sm" />
          <RiskBadge level="HIGH" size="sm" />
          <RiskBadge level={null} size="sm" />
        </Row>
      </Section>

      <Section id="feedback" title="Loading, error and messages">
        <div className="grid gap-6 md:grid-cols-2">
          <Card aria-label="Loading state example">
            <LoadingState label="Assessing payment" />
          </Card>
          <Card aria-label="Error state example">
            <CardBody>
              <ErrorState
                titleAs="h3"
                title="Could not load transactions"
                message="The server took too long to respond. It may be starting up; please try again."
                requestId="3f2c9a1b7d4e4c0f"
                onRetry={() => {}}
              />
            </CardBody>
          </Card>
        </div>
        <div className="space-y-3">
          <InlineAlert tone="info" title="Simulated payments">
            SakshamPay is not connected to UPI or any bank.
          </InlineAlert>
          <InlineAlert tone="success" title="Beneficiary saved" />
          <InlineAlert tone="danger" title="Invalid email or password.">
            Check your details and try again.
          </InlineAlert>
          <InlineAlert tone="neutral">The server may take a few seconds to wake up.</InlineAlert>
        </div>
      </Section>

      <Section id="layout" title="Layout">
        <div className="space-y-3 text-sm">
          {[
            ['narrow', 'max-w-xl · 576px · forms, payment, risk review'],
            ['default', 'max-w-6xl · 1152px · most pages'],
            ['wide', 'max-w-7xl · 1280px · data tables'],
          ].map(([size, meta]) => (
            <PageContainer
              key={size}
              size={size}
              className="rounded-md border border-dashed border-line-strong py-3 text-ink-muted"
            >
              <span className="font-mono text-ink">{size}</span> · {meta}
            </PageContainer>
          ))}
        </div>
        <p className="text-sm text-ink-muted">
          Breakpoints: sm 640px, md 768px, lg 1024px, xl 1280px. Design from 360px up. Side padding 16px, 24px from
          640px, 32px from 1024px.
        </p>
      </Section>
    </PageContainer>
  )
}
