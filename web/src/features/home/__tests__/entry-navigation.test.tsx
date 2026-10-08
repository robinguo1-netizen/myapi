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
import { after, describe, test } from 'node:test'

import { Window } from 'happy-dom'

const domWindow = new Window({ url: 'http://localhost/' })
domWindow.document.write('<!doctype html><html><body></body></html>')
const domGlobals = [
  'window',
  'self',
  'location',
  'history',
  'document',
  'navigator',
  'HTMLElement',
  'HTMLButtonElement',
  'HTMLAnchorElement',
  'SVGElement',
  'Node',
  'Element',
  'Event',
  'MouseEvent',
  'KeyboardEvent',
  'MutationObserver',
  'IntersectionObserver',
  'requestAnimationFrame',
  'cancelAnimationFrame',
  'getComputedStyle',
  'scrollTo',
  'localStorage',
  'Image',
] as const
const previousGlobals = new Map(
  domGlobals.map((key) => [
    key,
    Object.getOwnPropertyDescriptor(globalThis, key),
  ])
)
for (const key of domGlobals) {
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value: domWindow[key],
  })
}

const { act } = await import('react')
const { createRoot } = await import('react-dom/client')
const {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} = await import('@tanstack/react-router')
const { createInstance } = await import('i18next')
const { I18nextProvider } = await import('react-i18next')
const { Hero } = await import('../components/sections/hero')
const { Home } = await import('..')
const { QueryClient, QueryClientProvider } =
  await import('@tanstack/react-query')
const { api } = await import('@/lib/api')
const { useAuthStore } = await import('@/stores/auth-store')
const { default: en } = await import('@/i18n/locales/en.json')
const { default: zh } = await import('@/i18n/locales/zh.json')
const { useSystemConfigStore } = await import('@/stores/system-config-store')
const reactTestGlobals = globalThis as typeof globalThis & {
  IS_REACT_ACT_ENVIRONMENT?: boolean
}
const previousActEnvironment = reactTestGlobals.IS_REACT_ACT_ENVIRONMENT
reactTestGlobals.IS_REACT_ACT_ENVIRONMENT = true

describe('Landing page entry navigation', () => {
  after(() => {
    domWindow.close()
    for (const key of domGlobals) {
      const previous = previousGlobals.get(key)
      if (previous) Object.defineProperty(globalThis, key, previous)
      else Reflect.deleteProperty(globalThis, key)
    }
    reactTestGlobals.IS_REACT_ACT_ENVIRONMENT = previousActEnvironment
  })

  for (const scenario of [
    {
      name: 'anonymous visitors reach sign in when registration is disabled',
      isAuthenticated: false,
      registerEnabled: false,
      destination: '/sign-in',
    },
    {
      name: 'anonymous visitors reach sign up when registration is enabled',
      isAuthenticated: false,
      registerEnabled: true,
      destination: '/sign-up',
    },
    {
      name: 'authenticated visitors reach their dashboard with registration disabled',
      isAuthenticated: true,
      registerEnabled: false,
      destination: '/dashboard',
    },
  ] as const) {
    test(scenario.name, async () => {
      const i18n = createInstance()
      await i18n.init({
        lng: 'en',
        resources: { en, zhCN: zh },
        initAsync: false,
      })
      const rootRoute = createRootRoute()
      const homeRoute = createRoute({
        getParentRoute: () => rootRoute,
        path: '/',
        component: () => <Hero {...scenario} />,
      })
      const destinationRoute = createRoute({
        getParentRoute: () => rootRoute,
        path: scenario.destination,
        component: () => <h1>Destination reached</h1>,
      })
      const router = createRouter({
        routeTree: rootRoute.addChildren([homeRoute, destinationRoute]),
        history: createMemoryHistory({ initialEntries: ['/'] }),
      })
      const container = document.createElement('div')
      document.body.append(container)
      const root = createRoot(container)

      try {
        await act(async () => {
          await router.load()
          root.render(
            <I18nextProvider i18n={i18n}>
              <RouterProvider router={router} />
            </I18nextProvider>
          )
        })
        const startLink = [...container.querySelectorAll('a')].find((link) =>
          link.textContent?.includes('Get Started')
        )
        assert.ok(startLink, 'the primary action is an accessible link')
        assert.equal(startLink.getAttribute('href'), scenario.destination)

        await act(async () => {
          startLink.dispatchEvent(
            new MouseEvent('click', {
              bubbles: true,
              cancelable: true,
              button: 0,
            })
          )
        })
        await act(async () => {
          await router.load()
        })
        assert.equal(router.state.location.pathname, scenario.destination)
        assert.equal(
          container.querySelector('h1')?.textContent,
          'Destination reached'
        )
      } finally {
        await act(async () => root.unmount())
        container.remove()
      }
    })
  }

  for (const registerEnabled of [false, true]) {
    test(`home header and hero reach ${registerEnabled ? 'sign up' : 'sign in'} when registration is ${registerEnabled ? 'enabled' : 'disabled'}`, async () => {
      const destination = registerEnabled ? '/sign-up' : '/sign-in'
      const originalAdapter = api.defaults.adapter
      const originalAuth = useAuthStore.getState()
      const originalSystemConfig = useSystemConfigStore.getState()
      const queryClient = new QueryClient()
      queryClient.setQueryData(['status'], {
        register_enabled: registerEnabled,
      })
      queryClient.setQueryData(['notice'], { success: true, data: '' })
      api.defaults.adapter = async (config) => {
        assert.equal(config.url, '/api/home_page_content')
        return {
          data: { success: true, data: '' },
          status: 200,
          statusText: 'OK',
          headers: {},
          config,
        }
      }
      useAuthStore.getState().auth.reset()
      localStorage.setItem(
        'system-config-storage',
        JSON.stringify({
          state: {
            config: {
              ...originalSystemConfig.config,
              systemName: 'RS API',
              logo: '/rs-logo.svg',
            },
            loadedLogoUrl: '/rs-logo.svg',
          },
          version: 0,
        })
      )
      await useSystemConfigStore.persist.rehydrate()
      assert.equal(
        useSystemConfigStore.getState().config.systemName,
        'cheapersafer.si'
      )
      assert.equal(
        useSystemConfigStore.getState().config.logo,
        '/cheapersafer-logo.svg'
      )
      useSystemConfigStore.getState().setLoading(false)
      const i18n = createInstance()
      await i18n.init({
        lng: 'en',
        resources: { en, zhCN: zh },
        initAsync: false,
      })
      const rootRoute = createRootRoute()
      const homeRoute = createRoute({
        getParentRoute: () => rootRoute,
        path: '/',
        component: Home,
      })
      const destinationRoute = createRoute({
        getParentRoute: () => rootRoute,
        path: destination,
        component: () => <h1>Destination reached</h1>,
      })
      const router = createRouter({
        routeTree: rootRoute.addChildren([homeRoute, destinationRoute]),
        history: createMemoryHistory({ initialEntries: ['/'] }),
      })
      const container = document.createElement('div')
      document.body.append(container)
      const root = createRoot(container)

      try {
        await act(async () => {
          await router.load()
          root.render(
            <QueryClientProvider client={queryClient}>
              <I18nextProvider i18n={i18n}>
                <RouterProvider router={router} />
              </I18nextProvider>
            </QueryClientProvider>
          )
        })
        assert.equal(
          container.querySelector('h1')?.textContent,
          'Make every Tokencheaper, and safer.'
        )
        await act(async () => {
          await i18n.changeLanguage('zhCN')
        })
        assert.equal(
          container.querySelector('h1')?.textContent,
          '让每一枚 Token，更省，也更安心。'
        )
        assert.ok(
          container.querySelector(
            'img[alt="薄荷色玻璃盾牌与绿色环带守护 AI Token"]'
          )
        )
        await act(async () => {
          await i18n.changeLanguage('en')
        })
        const pricingLink = [...container.querySelectorAll('a')].find((link) =>
          link.textContent?.includes('View models and pricing')
        )
        assert.equal(pricingLink?.getAttribute('href'), '/pricing')
        const header = container.querySelector('header')
        assert.ok(header, 'the public header is visible')
        assert.equal(
          [...header.querySelectorAll('a')].some((link) =>
            link.textContent?.includes('Developer documentation')
          ),
          false,
          'the landing navigation does not send visitors to upstream docs'
        )
        assert.equal(
          header.querySelector('img')?.getAttribute('src'),
          '/cheapersafer-logo.svg'
        )
        assert.equal(
          container.querySelector('footer img')?.getAttribute('src'),
          '/cheapersafer-logo.svg'
        )
        const startLinks = [...container.querySelectorAll('a')].filter((link) =>
          link.textContent?.includes('Get Started')
        )
        assert.equal(
          startLinks.length,
          3,
          'desktop, mobile and hero entry links exist'
        )
        for (const link of startLinks) {
          assert.equal(link.getAttribute('href'), destination)
        }
        await act(async () => {
          startLinks[0].dispatchEvent(
            new MouseEvent('click', {
              bubbles: true,
              cancelable: true,
              button: 0,
            })
          )
        })
        await act(async () => {
          await router.load()
        })
        assert.equal(router.state.location.pathname, destination)
        assert.equal(
          container.querySelector('h1')?.textContent,
          'Destination reached'
        )
      } finally {
        await act(async () => root.unmount())
        container.remove()
        queryClient.clear()
        api.defaults.adapter = originalAdapter
        useAuthStore.setState(originalAuth)
        useSystemConfigStore.setState(originalSystemConfig)
        localStorage.clear()
      }
    })
  }
})
