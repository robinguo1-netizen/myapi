/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

For commercial licensing, please contact support@quantumnous.com
*/
import assert from 'node:assert/strict'
import { describe, test } from 'node:test'

import { createInstance } from 'i18next'
import { renderToStaticMarkup } from 'react-dom/server'
import { I18nextProvider } from 'react-i18next'

import { Features } from '../components/sections/features'
import { HowItWorks } from '../components/sections/how-it-works'

async function renderLandingSection(section: React.ReactNode) {
  const i18n = createInstance()
  await i18n.init({ lng: 'en', resources: {}, initAsync: false })
  return renderToStaticMarkup(
    <I18nextProvider i18n={i18n}>{section}</I18nextProvider>
  )
}

describe('cheapersafer landing page sections', () => {
  test('presents exactly the three approved business value propositions', async () => {
    const markup = await renderLandingSection(<Features />)

    assert.match(markup, /One API, multiple models/)
    assert.match(markup, /Keys and quotas under control/)
    assert.match(markup, /Usage and costs made clear/)
    assert.ok(markup.includes('md:grid-cols-3'))
  })

  test('presents onboarding as an ordered three-step flow', async () => {
    const markup = await renderLandingSection(<HowItWorks />)

    assert.equal((markup.match(/<li/g) ?? []).length, 3)
    assert.match(markup, /Register and add balance/)
    assert.match(markup, /Create an API key/)
    assert.match(markup, /Make your first call/)
  })
})
