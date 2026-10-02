import { api, apiFailure } from './client'
import type { Bot, Group, Account, Phone } from './management'

export async function allBots() {
  const items: Bot[] = []
  for (let page = 1; ; page++) {
    const result = await api.GET('/api/bots', { params: { query: { page, page_size: 200 } } })
    if (!result.data) throw apiFailure(result.error, result.response)
    items.push(...result.data.items)
    if (items.length >= result.data.total) return items
  }
}


export async function allGroups() {
  const items: Group[] = []
  for (let page = 1; ; page++) {
    const result = await api.GET('/api/groups', { params: { query: { page, page_size: 200 } } })
    if (!result.data) throw apiFailure(result.error, result.response)
    items.push(...result.data.items)
    if (items.length >= result.data.total) return items
  }
}

export async function allAccounts() {
  const items: Account[] = []
  for (let page = 1; ; page++) {
    const result = await api.GET('/api/accounts', { params: { query: { page, page_size: 200 } } })
    if (!result.data) throw apiFailure(result.error, result.response)
    items.push(...result.data.items)
    if (items.length >= result.data.total) return items
  }
}

export async function allPhones() {
  const items: Phone[] = []
  for (let page = 1; ; page++) {
    const result = await api.GET('/api/phones', { params: { query: { page, page_size: 200 } } })
    if (!result.data) throw apiFailure(result.error, result.response)
    items.push(...result.data.items)
    if (items.length >= result.data.total) return items
  }
}
