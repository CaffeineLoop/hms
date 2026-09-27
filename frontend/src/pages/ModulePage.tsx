/** Navigation placeholder for modules delivered in later UI stages (no functionality implied). */
import type { NavItem } from '../components/shell/navigation'
import { Card, EmptyState, LinkButton, PageHeader } from '../components/ui'

export function ModulePage({ item }: { item: NavItem }) {
  const stage = item.planned === 'UI-1' ? 'UI-1 — Patients & Clinical Records' : 'a later UI stage'
  return (
    <>
      <PageHeader title={item.label} description={item.summary}
        breadcrumbs={[{ label: 'Dashboard', to: '/' }, { label: item.label }]} />
      <Card>
        <EmptyState icon={item.icon} title="This module's interface is not built yet"
          description={<>The {item.label.toLowerCase()} screens are scheduled for {stage}. The underlying HMS services already
            exist and are protected by the same permissions shown in the navigation.</>}
          action={<LinkButton to="/" variant="secondary" icon="chevronLeft">Back to dashboard</LinkButton>} />
      </Card>
    </>
  )
}
