import { GridSkeleton } from '../../components/skeletons';

/**
 * Scoped to the `/registry` list by the `(list)` route group on purpose.
 *
 * As `registry/loading.tsx` this Suspense-wrapped the whole `/registry/*`
 * subtree, so a request for `/registry/<slug>` flushed the 200 shell before
 * `[slug]/layout.tsx` had finished looking the mod up — and a `notFound()`
 * after the response is committed can no longer change the status. Every dead
 * mod URL therefore answered 200 with an empty page (a soft 404) while its
 * sibling `/c/<slug>`, which has no parent loading file, answered a correct
 * 404. The route group keeps the skeleton for the list and leaves `[slug]` to
 * its own `loading.tsx`.
 */
export default function Loading() {
  return <GridSkeleton />;
}
