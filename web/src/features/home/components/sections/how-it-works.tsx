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
import { Code2, KeyRound, WalletCards } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { AnimateInView } from '@/components/animate-in-view'

export function HowItWorks() {
  const { t } = useTranslation()
  const steps = [
    {
      title: t('Register and add balance'),
      description: t(
        'Create your account and preload the balance you want to use.'
      ),
      icon: WalletCards,
    },
    {
      title: t('Create an API key'),
      description: t('Set up a dedicated key and quota for your application.'),
      icon: KeyRound,
    },
    {
      title: t('Make your first call'),
      description: t(
        'Use the unified endpoint to send your first model request.'
      ),
      icon: Code2,
    },
  ]

  return (
    <section className='bg-white px-6 py-20 text-[#07182e] md:py-28'>
      <div className='mx-auto max-w-7xl'>
        <AnimateInView className='text-center'>
          <p className='text-xs font-semibold tracking-[0.16em] text-[#0067d8] uppercase'>
            {t('Start in three steps')}
          </p>
          <h2 className='mt-4 text-3xl font-semibold tracking-[-0.03em] md:text-4xl'>
            {t('From account to first request')}
          </h2>
        </AnimateInView>

        <div className='relative mt-14'>
          <div
            aria-hidden='true'
            className='absolute top-7 right-[17%] left-[17%] hidden h-px bg-[#dce7f2] md:block'
          />
          <ol className='relative grid gap-8 md:grid-cols-3 md:gap-10'>
            {steps.map((step, index) => {
              const Icon = step.icon
              return (
                <AnimateInView
                  key={step.title}
                  delay={index * 120}
                  as='li'
                  className='relative text-center'
                >
                  <div className='relative mx-auto flex size-14 items-center justify-center rounded-2xl border border-[#dce7f2] bg-white text-[#0073ed] shadow-sm'>
                    <Icon className='size-5' strokeWidth={1.8} />
                    <span className='absolute -top-2 -right-2 flex size-6 items-center justify-center rounded-full bg-[#07182e] text-[11px] font-semibold text-white'>
                      {index + 1}
                    </span>
                  </div>
                  <h3 className='mt-6 text-lg font-semibold'>{step.title}</h3>
                  <p className='mx-auto mt-3 max-w-xs text-sm leading-7 text-[#526579]'>
                    {step.description}
                  </p>
                </AnimateInView>
              )
            })}
          </ol>
        </div>
      </div>
    </section>
  )
}
