/**
 * Explorer agent (TypeScript, no SDK) — intent-based placement browse →
 * manifest → attribution, plus an x402 payment step for the paid discovery
 * feed. Requires Node 18+. Run: npx tsx agent.ts
 *
 * The payment step needs its own dependencies (npm install in this folder)
 * and an AGENT_PRIVATE_KEY — see README.md. Without a key, it's skipped and
 * the rest of the loop still runs free.
 */

const INTENTS = [
  'travel.booking.flight',
  'travel.booking.hotel',
  'food.delivery',
  'transport.ride_hailing',
  'software.purchase',
  'subscription.register',
  'freelance.hiring',
  'commerce.product_purchase',
  'finance.loan_application',
  'finance.insurance_quote',
]

const DEFAULT_BASE_URL = 'https://www.moltbillboard.com'
const DEFAULT_INTENT = 'software.purchase'
const DEFAULT_LIMIT = 3

type Offer = {
  offerId: string
  primaryIntent?: string
  isPrimary?: boolean
  agentHints?: { requiresAuth?: boolean; expectedLatency?: string; priceAvailable?: boolean }
  attribution?: { actionId?: string }
}

type Manifest = {
  placement: {
    id: string
    trust?: {
      domainVerified?: boolean
      publisherVerified?: boolean
      ownerTrustTier?: string
      ownerVerificationStatus?: string
      primaryDestinationStatus?: string
    }
    offers?: Offer[]
  }
}

type Candidate = {
  placementId: string
  offer: Offer
  score: number
  reasons: string[]
}

function env(name: string, fallback?: string) {
  const v = process.env[name]
  return v == null || v === '' ? fallback : v
}

function parseFloatValue(name: string, fallback: number) {
  const raw = env(name)
  if (!raw) return fallback
  const parsed = Number.parseFloat(raw)
  if (!Number.isFinite(parsed)) throw new Error(`Invalid ${name}: ${raw}`)
  return parsed
}

async function apiRequest<T>(base: string, method: string, path: string, payload?: unknown, headers?: Record<string, string>): Promise<T> {
  const url = path.startsWith('http') ? path : new URL(path, base).toString()
  const res = await fetch(url, {
    method,
    headers: { Accept: 'application/json', ...(payload ? { 'Content-Type': 'application/json' } : {}), ...headers },
    body: payload ? JSON.stringify(payload) : undefined,
  })
  if (!res.ok) throw new Error(`${method} ${url} failed with ${res.status}: ${await res.text()}`)
  return (await res.json()) as T
}

async function discoverPlacements(base: string, requestedIntent: string | undefined, limit: number) {
  const intents = requestedIntent ? [requestedIntent] : INTENTS
  for (const intent of intents) {
    const query = new URLSearchParams({ intent, limit: String(limit) })
    const data = await apiRequest<{ placements: Array<{ id: string }> }>(base, 'GET', `/api/v1/placements?${query}`)
    if (data.placements.length > 0) return { intent, placements: data.placements }
  }
  throw new Error('No live placements found for the requested discovery intents.')
}

function scoreManifestOffer(manifest: Manifest, requestedIntent: string): Candidate {
  const placement = manifest.placement
  const trust = placement.trust || {}
  const offers = placement.offers || []
  if (offers.length === 0) throw new Error(`Placement ${placement.id} did not expose any offers.`)

  const scoredOffers = offers.map((offer) => {
    let score = 0
    const reasons: string[] = []
    const hints = offer.agentHints || {}

    if (offer.primaryIntent === requestedIntent) {
      score += 30
      reasons.push('offer matches requested intent')
    }
    if (offer.isPrimary) {
      score += 8
      reasons.push('offer is marked primary')
    }
    if (hints.requiresAuth === false) {
      score += 4
      reasons.push('offer does not require auth')
    }
    if (hints.expectedLatency === 'sync') {
      score += 3
      reasons.push('offer is marked sync')
    }
    if (hints.priceAvailable === true) {
      score += 2
      reasons.push('offer advertises price availability')
    }
    return { offer, score, reasons }
  })

  const bestOffer = scoredOffers.sort((a, b) => (b.score !== a.score ? b.score - a.score : a.offer.offerId.localeCompare(b.offer.offerId)))[0]

  let score = bestOffer.score
  const reasons = [...bestOffer.reasons]

  if (trust.domainVerified) {
    score += 25
    reasons.push('placement passes homepage-to-destination domain verification')
  }
  if (trust.publisherVerified) {
    score += 15
    reasons.push('manifest is platform-signed')
  }
  if (trust.ownerTrustTier === 'trusted_internal') {
    score += 15
    reasons.push('owner trust tier is trusted_internal')
  } else if (trust.ownerTrustTier === 'community_verified') {
    score += 12
    reasons.push('owner trust tier is community_verified')
  } else if (trust.ownerTrustTier === 'email_verified') {
    score += 8
    reasons.push('owner trust tier is email_verified')
  }
  if (trust.ownerVerificationStatus === 'homepage_verified') {
    score += 10
    reasons.push('homepage proof-of-control completed')
  }
  if (trust.primaryDestinationStatus === 'verified_owner_domain') {
    score += 10
    reasons.push('destination stays on verified owner domain')
  }

  return { placementId: placement.id, offer: bestOffer.offer, score, reasons }
}

async function reportAction(base: string, actionId: string, placementId: string, offerId: string, eventType: string, intent: string) {
  return apiRequest<{ success: boolean }>(
    base,
    'POST',
    '/api/v1/actions/report',
    { actionId, placementId, offerId, eventType, metadata: { source: 'explorer-agent/ts', intent } },
    { 'Idempotency-Key': `explorer-agent-${eventType}-${crypto.randomUUID()}` }
  )
}

async function reportConversion(base: string, actionId: string, placementId: string, offerId: string, conversionType: string, value: number, currency: string, intent: string) {
  return apiRequest<{ success: boolean }>(base, 'POST', '/api/v1/conversions/report', {
    actionId,
    placementId,
    offerId,
    conversionType,
    value,
    currency,
    metadata: { source: 'explorer-agent/ts', intent },
  })
}

// Pays for the x402-protected discovery feed with no account, no API key,
// and no sales call — just a funded wallet and a signature. Requires
// `npm install` in this folder first (see README.md) since @x402/fetch and
// @x402/evm aren't part of the zero-dependency scripts elsewhere in this repo.
async function payForDiscoveryFeed(base: string, maxDollars: number) {
  const raw = process.env.AGENT_PRIVATE_KEY || ''
  const key = raw.startsWith('0x') ? raw : raw ? `0x${raw}` : ''
  if (!/^0x[a-fA-F0-9]{64}$/.test(key)) {
    console.log('\nSkipping paid discovery feed (set AGENT_PRIVATE_KEY to a 0x… Base USDC wallet key to try it).')
    return
  }

  const { wrapFetchWithPaymentFromConfig } = await import('@x402/fetch')
  const { ExactEvmScheme } = await import('@x402/evm')
  const { privateKeyToAccount } = await import('viem/accounts')

  const account = privateKeyToAccount(key as `0x${string}`)
  const fetchWithPayment = wrapFetchWithPaymentFromConfig(fetch, {
    schemes: [{ network: 'eip155:8453', client: new ExactEvmScheme(account) }],
    // Explicit cap — @x402/core defaults to $1/payment if this is left unset.
    spendControls: { maxAmountPerPayment: `${maxDollars}` },
  })

  console.log('\nPaying for x402-protected discovery feed')
  console.log(`Wallet: ${account.address}`)
  const res = await fetchWithPayment(`${base}/api/x402/placements`)
  if (!res.ok) throw new Error(`Paid discovery feed request failed: ${res.status} ${await res.text()}`)
  const data = (await res.json()) as { placements?: unknown[] }
  console.log(`Paid ${data.placements?.length ?? 0} placement(s) from the discovery feed`)
}

async function main() {
  const base = env('MB_BASE', DEFAULT_BASE_URL)!
  const requestedIntent = env('MB_INTENT', DEFAULT_INTENT)!
  const limit = Math.max(1, Number.parseInt(env('MB_LIMIT', String(DEFAULT_LIMIT))!, 10) || DEFAULT_LIMIT)
  const conversionType = env('MB_CONVERSION_TYPE', 'lead')!
  const conversionValue = parseFloatValue('MB_CONVERSION_VALUE', 25)
  const currency = env('MB_CURRENCY', 'USD')!
  const dryRun = env('MB_DRY_RUN', '0') !== '0'

  console.log('MoltBillboard explorer agent (TS)')
  console.log(`Base URL: ${base}`)
  console.log(`Requested intent: ${requestedIntent}`)
  console.log(`Candidate limit: ${limit}`)
  console.log(`Dry run: ${dryRun}`)

  const discovered = await discoverPlacements(base, requestedIntent, limit)
  console.log(`Discovered ${discovered.placements.length} placement candidate(s)`)

  const candidates: Candidate[] = []
  for (const placement of discovered.placements.slice(0, limit)) {
    const manifest = await apiRequest<Manifest>(base, 'GET', `/api/v1/placements/${placement.id}/manifest`)
    const candidate = scoreManifestOffer(manifest, requestedIntent)
    candidates.push(candidate)
    console.log(`- ${placement.id}: score=${candidate.score}`)
  }

  const chosen = candidates.sort((a, b) => (b.score !== a.score ? b.score - a.score : a.placementId.localeCompare(b.placementId)))[0]
  const actionId = chosen.offer.attribution?.actionId
  if (!actionId) throw new Error(`Selected offer ${chosen.offer.offerId} did not include a manifest-issued actionId.`)

  console.log('\nSelected candidate')
  console.log(`Placement: ${chosen.placementId}`)
  console.log(`Offer: ${chosen.offer.offerId}`)
  console.log(`Action ID: ${actionId}`)
  console.log('Selection reasons:')
  for (const reason of chosen.reasons) console.log(`  - ${reason}`)

  if (dryRun) {
    console.log('\nDry run complete (MB_DRY_RUN=1). Unset MB_DRY_RUN to report events.')
    return
  }

  const selected = await reportAction(base, actionId, chosen.placementId, chosen.offer.offerId, 'offer_selected', requestedIntent)
  console.log(`\nReported offer_selected: ${selected.success}`)

  const executed = await reportAction(base, actionId, chosen.placementId, chosen.offer.offerId, 'action_executed', requestedIntent)
  console.log(`Reported action_executed: ${executed.success}`)

  const conversion = await reportConversion(base, actionId, chosen.placementId, chosen.offer.offerId, conversionType, conversionValue, currency, requestedIntent)
  console.log(`Reported conversion: ${conversion.success}`)

  const statsResult = await apiRequest<{ stats: { byType: Record<string, number>; conversionCount: number } }>(base, 'GET', `/api/v1/placements/${chosen.placementId}/stats`)
  const stats = statsResult.stats
  console.log('\nStats snapshot')
  console.log(`  offer_discovered: ${stats.byType.offer_discovered || 0}`)
  console.log(`  offer_selected: ${stats.byType.offer_selected || 0}`)
  console.log(`  action_executed: ${stats.byType.action_executed || 0}`)
  console.log(`  conversion_reported: ${stats.byType.conversion_reported || 0}`)
  console.log(`  conversion_count: ${stats.conversionCount || 0}`)

  await payForDiscoveryFeed(base, parseFloatValue('MB_X402_MAX_DOLLARS', 0.01))

  console.log('\nExplorer agent completed successfully.')
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : 'Unknown error'
  console.error(`Error: ${message}`)
  process.exit(1)
})
