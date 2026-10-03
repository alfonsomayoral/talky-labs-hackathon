import type { Company } from '@/domain/types'
import { groupName, monthLabel } from './groupName'

const company = (role: string, name: string) => ({ role, name }) as Company

describe('groupName', () => {
  it('names the group after the first word of the holding', () => {
    const companies = [
      company('construction', 'Hidrocon Obras, S.L.'),
      company('holding', 'Kalmora Infraestructuras y Servicios, S.A.'),
    ]
    expect(groupName(companies)).toBe('Grupo Kalmora')
  })

  it('drops punctuation glued to the first word', () => {
    expect(groupName([company('holding', 'Acme, S.A.')])).toBe('Grupo Acme')
  })

  it('returns null without a holding', () => {
    expect(groupName([company('construction', 'Kalmora Construcción, S.A.U.')])).toBeNull()
    expect(groupName(undefined)).toBeNull()
  })
})

describe('monthLabel', () => {
  it('spells the month in Spanish, capitalized', () => {
    expect(monthLabel('2026-07')).toBe('Julio 2026')
    expect(monthLabel('2026-01-31')).toBe('Enero 2026')
  })

  it('shows a dash for a missing month', () => {
    expect(monthLabel('')).toBe('—')
  })
})
