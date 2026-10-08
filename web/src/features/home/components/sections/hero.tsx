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
import { ArrowRight, Check, ShieldCheck, Wallet } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'

interface HeroProps {
  isAuthenticated?: boolean
  registerEnabled?: boolean
}

export function Hero(props: HeroProps) {
  const { t } = useTranslation()
  const guestDestination =
    props.registerEnabled === false ? '/sign-in' : '/sign-up'
  const primaryDestination = props.isAuthenticated
    ? '/dashboard'
    : guestDestination
  const supportingPoints = [
    t('Usage-based billing'),
    t('Keys and quotas under control'),
    t('Usage and costs made clear'),
  ]

  return (
    <section
      className='relative overflow-hidden bg-[#f7f8f2] px-6 pt-32 pb-12 text-[#143d32] md:pt-36 md:pb-20'
      aria-labelledby='cheapersafer-hero-title'
    >
      <div className='relative mx-auto grid w-full max-w-7xl items-center gap-8 lg:min-h-[570px] lg:grid-cols-[1.05fr_1fr] lg:gap-0'>
        <div className='relative z-10 max-w-[42rem]'>
          <p className='landing-animate-fade-up mb-7 inline-flex items-center gap-2.5 rounded-full border border-[#d8e3d8] bg-white/70 px-4 py-2 text-xs font-semibold tracking-[0.06em] text-[#236447] opacity-0'>
            <span
              aria-hidden='true'
              className='size-1.5 rounded-full bg-[#1d7658]'
            />
            {t('Cheaper to use. Safer to build.')}
          </p>
          <h1
            id='cheapersafer-hero-title'
            className='landing-animate-fade-up text-[clamp(2.5rem,5.2vw,4.5rem)] leading-[1.2] font-semibold tracking-[-0.045em] opacity-0'
            style={{ animationDelay: '70ms' }}
          >
            <span className='block'>{t('Make every Token')}</span>
            <span className='mt-1 block text-[#1d7658]'>
              {t('cheaper, and safer.')}
            </span>
          </h1>
          <p
            className='landing-animate-fade-up mt-7 max-w-[33rem] text-base leading-8 text-[#526b60] opacity-0 md:text-lg'
            style={{ animationDelay: '140ms' }}
          >
            {t(
              'One API for multiple AI models. Pay for what you use, manage keys and quotas, and see where every Token goes. Built for businesses and individuals.'
            )}
          </p>
          <div
            className='landing-animate-fade-up mt-9 flex flex-col gap-3 opacity-0 sm:flex-row'
            style={{ animationDelay: '210ms' }}
          >
            <Button
              className='group h-12 rounded-xl bg-[#143d32] px-6 text-sm font-semibold text-white shadow-[0_8px_20px_rgba(20,61,50,0.12)] hover:bg-[#1d7658]'
              render={<Link to={primaryDestination} />}
            >
              {t('Get Started')}
              <ArrowRight
                aria-hidden='true'
                className='ml-1.5 size-4 transition-transform group-hover:translate-x-0.5'
              />
            </Button>
            <Button
              variant='outline'
              className='h-12 rounded-xl border-[#cbd9cd] bg-transparent px-6 text-sm font-semibold text-[#143d32] hover:border-[#1d7658] hover:bg-[#e8f0e5] hover:text-[#143d32]'
              render={<Link to='/pricing' />}
            >
              {t('View models and pricing')}
            </Button>
          </div>
          <ul
            className='landing-animate-fade-up mt-7 flex flex-wrap gap-x-5 gap-y-3 text-xs text-[#526b60] opacity-0'
            style={{ animationDelay: '280ms' }}
          >
            {supportingPoints.map((point) => (
              <li key={point} className='flex items-center gap-1.5'>
                <Check
                  aria-hidden='true'
                  className='size-3.5 text-[#1d7658]'
                  strokeWidth={2.5}
                />
                {point}
              </li>
            ))}
          </ul>
        </div>
        <div className='relative mx-auto w-full max-w-xl lg:max-w-none'>
          <img
            src='/cheapersafer-hero.png'
            alt={t(
              'A mint glass shield protects AI tokens inside an efficient green routing loop'
            )}
            width={1536}
            height={1024}
            fetchPriority='high'
            className='aspect-[1.12] w-full rounded-[2rem] object-cover object-[75%_center] mix-blend-multiply'
          />
          <div className='absolute top-[12%] right-0 flex items-center gap-2.5 rounded-2xl border border-white/90 bg-white/90 px-4 py-3 text-sm shadow-[0_12px_32px_rgba(20,61,50,0.08)] backdrop-blur-sm'>
            <ShieldCheck aria-hidden='true' className='size-5 text-[#1d7658]' />
            <span>{t('Your keys. Your control.')}</span>
          </div>
          <div className='absolute bottom-[6%] left-0 flex items-center gap-2.5 rounded-2xl border border-white/90 bg-white/90 px-4 py-3 text-sm shadow-[0_12px_32px_rgba(20,61,50,0.08)] backdrop-blur-sm'>
            <Wallet aria-hidden='true' className='size-5 text-[#1d7658]' />
            <span>{t('Every Token, accounted for.')}</span>
          </div>
        </div>
      </div>
      <div className='mx-auto mt-10 flex max-w-7xl flex-wrap items-center justify-between gap-3 border-t border-[#d8e3d8] pt-6 text-xs text-[#526b60]'>
        <span>{t('A simpler way to connect with AI')}</span>
        <span className='font-mono text-[#236447]'>
          {t('One API / More possibilities')}
        </span>
      </div>
    </section>
  )
}
