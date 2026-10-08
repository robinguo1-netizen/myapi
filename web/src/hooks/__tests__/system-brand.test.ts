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

import { mapStatusDataToConfig } from '../use-system-config'

describe('cheapersafer application branding', () => {
  test('stock upstream status displays cheapersafer branding on every shared layout', () => {
    const config = mapStatusDataToConfig({
      system_name: 'New API',
      logo: '/logo.png',
    })

    assert.equal(config.systemName, 'cheapersafer.si')
    assert.equal(config.logo, '/cheapersafer-logo.svg')
  })

  for (const systemName of ['RS API', 'RS', undefined]) {
    test(`legacy or empty brand ${systemName} resolves to cheapersafer`, () => {
      const config = mapStatusDataToConfig({
        system_name: systemName,
        logo: '/rs-logo.svg',
      })
      assert.equal(config.systemName, 'cheapersafer.si')
      assert.equal(config.logo, '/cheapersafer-logo.svg')
    })
  }

  test('an explicitly configured system name and logo are preserved', () => {
    const config = mapStatusDataToConfig({
      system_name: 'Custom Brand',
      logo: 'https://example.com/custom.svg',
    })

    assert.equal(config.systemName, 'Custom Brand')
    assert.equal(config.logo, 'https://example.com/custom.svg')
  })
})
