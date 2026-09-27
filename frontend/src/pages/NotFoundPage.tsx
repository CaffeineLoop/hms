import { Card, EmptyState, LinkButton, PageHeader } from '../components/ui'

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not found" breadcrumbs={[{ label: 'Dashboard', to: '/' }, { label: 'Not found' }]} />
      <Card>
        <EmptyState icon="search" title="We couldn't find that page"
          description="The address may be mistyped, or the page may have moved."
          action={<LinkButton to="/" variant="secondary" icon="chevronLeft">Back to dashboard</LinkButton>} />
      </Card>
    </>
  )
}
