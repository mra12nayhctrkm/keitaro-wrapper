import { expect, test, type Page } from '@playwright/test'

/** What the fake Keitaro holds for a stream: offer_id -> share. */
async function keitaroOffers(page: Page, streamId: number): Promise<Record<number, number>> {
  const stream = await (await page.request.get(`/__fake/streams/${streamId}`)).json()
  return Object.fromEntries(stream.offers.map((o: { offer_id: number; share: number }) => [o.offer_id, o.share]))
}

async function pickOffer(page: Page, input: string, query: string, option: RegExp) {
  await page.getByLabel(input, { exact: true }).fill(query)
  await page.getByRole('option', { name: option }).click()
}

test('create a campaign, then edit, publish, cancel and undo offers', async ({ page }) => {
  // --- creator -------------------------------------------------------------
  await page.goto('/')
  await page.getByLabel('Name').fill('spring')
  await expect(page.getByText('Will be created as test_e2e_spring')).toBeVisible()
  await page.getByLabel('Geo').fill('au, mx')
  await pickOffer(page, 'Offer', 'fito', /FitoMishki/)
  await page.getByRole('button', { name: 'Create' }).click()

  await expect(page.getByRole('heading', { name: /test_e2e_spring/ })).toBeVisible()
  await expect(page.getByText('Geo AU, MX → Google')).toBeVisible()

  const created = (await (await page.request.get('/__fake/campaigns')).json())[0]
  const [geo, offers] = created.streams
  expect(geo.filters).toEqual([{ name: 'country', mode: 'accept', payload: ['AU', 'MX'] }])
  expect(geo.action_payload).toBe('https://google.com')
  expect(await keitaroOffers(page, offers.id)).toEqual({ 13: 100 })

  const card = page.getByRole('region', { name: 'Stream Offers' })

  // --- add + push --------------------------------------------------------
  await card.getByRole('combobox').fill('oxys')
  await page.getByRole('option', { name: /Oxys/ }).click()
  await card.getByRole('button', { name: 'Add' }).click()
  await expect(card.getByText('unpublished')).toBeVisible()
  await expect(card.getByText('50%')).toHaveCount(2)
  expect(await keitaroOffers(page, offers.id)).toEqual({ 13: 100 }) // still a draft

  await card.getByRole('button', { name: 'Push to Keitaro' }).click()
  await expect(card.getByText('unpublished')).toBeHidden()
  expect(await keitaroOffers(page, offers.id)).toEqual({ 13: 50, 14: 50 })

  // --- remove + cancel ---------------------------------------------------
  await card.getByRole('row', { name: /Oxys/ }).getByRole('button', { name: 'Remove' }).click()
  await expect(card.getByText('will be removed')).toBeVisible()
  await card.getByRole('button', { name: 'Cancel' }).click()
  await expect(card.getByText('will be removed')).toBeHidden()

  // --- history: undo the push ---------------------------------------------
  await card.getByRole('button', { name: 'History' }).click()
  const history = card.getByRole('list', { name: 'Publish history' })
  await expect(history.getByText('after: #13 50%, #14 50%')).toBeVisible()
  await history.getByRole('button', { name: 'Undo' }).click()
  await expect(card.getByText('will be removed')).toBeVisible()
  await card.getByRole('button', { name: 'Push to Keitaro' }).click()
  await expect(card.getByText('unpublished')).toBeHidden()
  expect(await keitaroOffers(page, offers.id)).toEqual({ 13: 100 })
  await expect(history.locator('li')).toHaveCount(2)
})

test('bulk replace previews and applies to the chosen streams', async ({ page }) => {
  await page.goto('/bulk')
  await page.getByLabel('Name has').fill('test_e2e_')
  await pickOffer(page, 'Replace', 'fito', /FitoMishki/)
  await pickOffer(page, 'With', '12', /BE_0008/)
  await page.getByRole('button', { name: 'Preview' }).click()
  await expect(page.getByText(/stream\(s\) use offer #13/)).toBeVisible()

  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Apply and publish' }).click()
  await expect(page.getByText('published').first()).toBeVisible()

  const campaigns = await (await page.request.get('/__fake/campaigns')).json()
  const offerStream = campaigns[0].streams[1]
  expect(Object.fromEntries(offerStream.offers.map((o: { offer_id: number; share: number }) => [o.offer_id, o.share]))).toEqual({ 12: 100 })
})
