import { Card, CardBody } from '../ui/Card'
import Skeleton from '../ui/Skeleton'

/**
 * Placeholder in the shape of the dashboard while the summary loads. The blocks are
 * decorative; screen readers hear the status message instead.
 */
export default function DashboardSkeleton() {
  return (
    <div aria-busy="true" className="space-y-6">
      <p role="status" className="sr-only">
        Loading your summary
      </p>
      <Card as="div">
        <CardBody>
          <Skeleton className="h-5 w-32" />
          <div className="mt-6 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((n) => (
              <div key={n} className="space-y-2">
                <Skeleton className="h-4 w-28" />
                <Skeleton className="h-8 w-24" />
                <Skeleton className="h-3 w-36" />
              </div>
            ))}
          </div>
        </CardBody>
      </Card>
      <Card as="div">
        <CardBody className="space-y-4">
          <Skeleton className="h-5 w-40" />
          {[0, 1, 2, 3, 4, 5, 6].map((n) => (
            <Skeleton key={n} className="h-4 w-full" />
          ))}
        </CardBody>
      </Card>
    </div>
  )
}
