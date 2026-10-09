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
import { DEFAULT_SYSTEM_NAME } from '@/lib/constants'
import { cn } from '@/lib/utils'

type BrandWordmarkProps = {
  className?: string
  fixedLight?: boolean
}

export function BrandWordmark(props: BrandWordmarkProps) {
  return (
    <img
      src='/cheapersafer-wordmark.svg'
      alt={DEFAULT_SYSTEM_NAME}
      width={1982}
      height={352}
      className={cn(
        'h-7 w-auto shrink-0 object-contain',
        !props.fixedLight && 'dark:brightness-0 dark:invert',
        props.className
      )}
    />
  )
}
