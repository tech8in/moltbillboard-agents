/**
 * DevScout (TypeScript, no SDK) — ad-units → manifest → attribution.
 * Requires Node 18+. Run: MB_DRY_RUN=1 npx tsx agent.ts
 */

const TARGET_INTENTS = new Set(['software.purchase', 'subscription.register'])
const DEFAULT_BASE = 'https://www.moltbillboard.com'
const DEFAULT_TOPIC = 'developer tools'

function env(name: string, fallback?: string) {
  const v = process.env[name]
  return v == null || v === '' ? fallback : v
}

async function discoverAdUnits(base: string, topic: string, limit: number) {
  const url = new URL('/api/v1/ad-units', base)
  url.searchParams.set('topic', topic)
  url.searchParams.set('limit', String(limit))
  url.searchParams.set('surface', 'api')
  const res = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(`ad-units HTTP ${res.status}`)
  const body = (await res.json()) as { adUnits?: Array<Record<string, string>> }
  return body.adUnits ?? []
}

function pickUnit(units: Array<Record<string, string>>) {
  const ranked = units
    .map((u) => {
      let score = 0
      if (u.primaryIntent && TARGET_INTENTS.has(u.primaryIntent)) score += 20
      if (u.actionEndpoint) score += 5
      return { u, score }
    })
    .sort((a, b) => b.score - a.score)
  return ranked[0]?.u ?? units[0]
}

async function main() {
  const base = env('MB_BASE', DEFAULT_BASE)!
  const topic = env('MB_TOPIC', DEFAULT_TOPIC)!
  const dryRun = env('MB_DRY_RUN', '1') !== '0'

  console.log('DevScout (TS)', { base, topic, dryRun })

  const units = await discoverAdUnits(base, topic, 5)
  if (!units.length) throw new Error('No ad units')
  const unit = pickUnit(units)
  const placementId = unit.placementId
  if (!placementId) throw new Error('Missing placementId')

  const manifestRes = await fetch(`${base}/api/v1/placements/${placementId}/manifest`)
  if (!manifestRes.ok) throw new Error(`manifest HTTP ${manifestRes.status}`)
  const envelope = (await manifestRes.json()) as { manifest?: { placement?: { offers?: Array<Record<string, unknown>> } } }
  const offers = envelope.manifest?.placement?.offers ?? []
  if (!offers.length) throw new Error('No offers')
  const offer = offers[0] as { offerId: string; attribution?: { actionId?: string } }
  const actionId = offer.attribution?.actionId
  if (!actionId) throw new Error('No actionId')

  console.log({ placementId, offerId: offer.offerId, actionId })

  if (dryRun) {
    console.log('Dry run complete (MB_DRY_RUN=1)')
    return
  }

  const idem = `devscout-${crypto.randomUUID()}`
  const actionRes = await fetch(`${base}/api/v1/actions/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idem },
    body: JSON.stringify({
      actionId,
      placementId,
      offerId: offer.offerId,
      eventType: 'offer_selected',
    }),
  })
  if (!actionRes.ok) throw new Error(`actions/report HTTP ${actionRes.status}`)
  console.log('offer_selected:', (await actionRes.json()) as { success?: boolean })
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
