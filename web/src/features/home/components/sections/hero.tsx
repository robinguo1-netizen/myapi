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
import { Link } from '@tanstack/react-router'
import { ArrowRight, Check } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import rsHeroImage from '@/assets/rs/rs-hero.png'
import { Button } from '@/components/ui/button'

interface HeroProps {
  isAuthenticated?: boolean
  registerEnabled?: boolean
}

export function Hero(props: HeroProps) {
  const { t, i18n } = useTranslation()
  const guestDestination =
    props.registerEnabled === false ? '/sign-in' : '/sign-up'
  const primaryDestination = props.isAuthenticated
    ? '/dashboard'
    : guestDestination
  const headline = t('Make AI integration simpler for businesses and individuals.')
  const chineseHeadlineParts = i18n.resolvedLanguage?.startsWith('zh')
    ? headline.match(/^(.*?，)(.*)$/)
    : null
  const supportingPoints = [
    t('Self-service signup'),
    t('Prepaid balance'),
    t('Usage-based billing'),
  ]

  return (
    <section
      className='relative flex min-h-[700px] items-center overflow-hidden bg-[#07182e] px-6 pt-24 pb-16 text-white md:min-h-[760px] md:pt-28 md:pb-20'
      aria-labelledby='rs-hero-title'
    >
      <img
        src={rsHeroImage}
        alt=''
        aria-hidden='true'
        className='absolute right-[-18%] bottom-0 h-auto w-[150%] max-w-none object-contain sm:inset-0 sm:h-full sm:w-full sm:object-cover sm:object-[62%_center] lg:object-center'
      />
      <div
        aria-hidden='true'
        className='absolute inset-0 bg-[linear-gradient(180deg,rgba(7,24,46,0.99)_0%,rgba(7,24,46,0.96)_58%,rgba(7,24,46,0.38)_100%)] sm:bg-[linear-gradient(90deg,rgba(7,24,46,0.99)_0%,rgba(7,24,46,0.92)_34%,rgba(7,24,46,0.4)_62%,rgba(7,24,46,0.02)_84%)]'
      />
      <div
        aria-hidden='true'
        className='absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-[#07182e] to-transparent'
      />

      <div className='relative mx-auto w-full max-w-7xl'>
        <div className='max-w-[42rem]'>
          <p className='landing-animate-fade-up mb-5 text-sm font-semibold tracking-[0.18em] text-[#72b9ff] uppercase opacity-0'>
            {t('Connect AI capabilities for businesses and individuals')}
          </p>
          <h1
            id='rs-hero-title'
            className='landing-animate-fade-up max-w-3xl text-[clamp(2.75rem,6vw,5.4rem)] leading-[1.04] font-semibold tracking-[-0.045em] opacity-0'
            style={{ animationDelay: '70ms' }}
          >
            {chineseHeadlineParts ? (
              <>
                {chineseHeadlineParts[1]}
                <span className='whitespace-nowrap'>
                  {chineseHeadlineParts[2]}
                </span>
              </>
            ) : (
              headline
            )}
          </h1>
          <p
            className='landing-animate-fade-up mt-7 max-w-[39rem] text-base leading-8 text-blue-50/76 opacity-0 md:text-lg'
            style={{ animationDelay: '140ms' }}
          >
            {t(
              'Connect multiple models through one unified API. Businesses and individuals can get started on their own, pay by usage, and keep usage and costs easy to understand.'
            )}
          </p>

          <div
            className='landing-animate-fade-up mt-9 flex flex-col gap-3 opacity-0 sm:flex-row'
            style={{ animationDelay: '210ms' }}
          >
            <Button
              className='group h-12 rounded-lg bg-[#0073ed] px-6 text-sm font-semibold text-white shadow-[0_12px_30px_rgba(0,115,237,0.28)] hover:bg-[#0067d8]'
              render={<Link to={primaryDestination} />}
            >
              {t('Get Started')}
              <ArrowRight className='ml-1.5 size-4 transition-transform group-hover:translate-x-0.5' />
            </Button>
            <Button
              variant='outline'
              className='h-12 rounded-lg border-white/28 bg-white/7 px-6 text-sm font-semibold text-white backdrop-blur-md hover:border-white/45 hover:bg-white/14 hover:text-white'
              render={<Link to='/pricing' />}
            >
              {t('View models and pricing')}
            </Button>
          </div>

          <ul
            className='landing-animate-fade-up mt-8 flex flex-wrap gap-x-6 gap-y-3 text-sm text-blue-50/74 opacity-0'
            style={{ animationDelay: '280ms' }}
          >
            {supportingPoints.map((point) => (
              <li key={point} className='flex items-center gap-2'>
                <span className='flex size-5 items-center justify-center rounded-full border border-[#34cf00]/40 bg-[#34cf00]/12 text-[#61e735]'>
                  <Check className='size-3' strokeWidth={2.5} />
                </span>
                {point}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}
