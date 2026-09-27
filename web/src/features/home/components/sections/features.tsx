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
import { BarChart3, KeyRound, Network } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { AnimateInView } from '@/components/animate-in-view'

export function Features() {
  const { t } = useTranslation()
  const features = [
    {
      title: t('One API, multiple models'),
      description: t(
        'Use one consistent integration to access the models businesses and individuals need.'
      ),
      icon: Network,
    },
    {
      title: t('Keys and quotas under control'),
      description: t(
        'Create separate API keys and set clear access limits for each use case.'
      ),
      icon: KeyRound,
    },
    {
      title: t('Usage and costs made clear'),
      description: t(
        'Review request logs, usage details, and balance changes from one place.'
      ),
      icon: BarChart3,
    },
  ]

  return (
    <section className='bg-[#f4f8fc] px-6 py-20 text-[#07182e] md:py-28'>
      <div className='mx-auto max-w-7xl'>
        <AnimateInView className='max-w-2xl'>
          <p className='text-xs font-semibold tracking-[0.16em] text-[#0067d8] uppercase'>
            {t('Built for practical adoption')}
          </p>
          <h2 className='mt-4 text-3xl font-semibold tracking-[-0.03em] md:text-4xl'>
            {t('The essentials for running AI APIs with confidence')}
          </h2>
        </AnimateInView>

        <div className='mt-12 grid gap-5 md:grid-cols-3'>
          {features.map((feature, index) => {
            const Icon = feature.icon
            return (
              <AnimateInView
                key={feature.title}
                delay={index * 100}
                className='rounded-2xl border border-[#dce7f2] bg-white p-7 shadow-[0_18px_50px_rgba(7,24,46,0.06)] md:p-8'
              >
                <div className='flex size-11 items-center justify-center rounded-xl bg-[#eaf4ff] text-[#0073ed]'>
                  <Icon className='size-5' strokeWidth={1.8} />
                </div>
                <h3 className='mt-8 text-lg font-semibold'>{feature.title}</h3>
                <p className='mt-3 text-sm leading-7 text-[#526579]'>
                  {feature.description}
                </p>
              </AnimateInView>
            )
          })}
        </div>
      </div>
    </section>
  )
}
