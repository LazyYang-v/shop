import { getCsrfToken, notifySessionExpired } from './auth'

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { credentials: 'same-origin', ...init })
  if (response.status === 401) notifySessionExpired()
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail ?? `请求失败 (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

async function mutate<T>(path: string, method: string, body?: unknown, extra: Record<string, string> = {}): Promise<T> {
  const token = await getCsrfToken()
  return request<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token, ...extra },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export type CartItem = { product_id: string; name: string; image_url: string; unit_price: string; quantity: number; selected: boolean; stock: number }
export type Cart = { items: CartItem[]; total: string }
export type Address = { id: string; recipient_name: string; phone: string; province: string; city: string; district: string; detail: string; is_default: boolean }
export type AddressInput = Omit<Address, 'id'>
export type Order = { id: string; status: string; total: string; created_at: string; paid_at: string | null; closed_at: string | null; close_reason: string | null; shipped_at: string | null; completed_at: string | null; shipping_company: string | null; tracking_number: string | null; expires_at: string; items: Array<{ product_id: string; image_url: string; name: string; quantity: number; unit_price: string; line_total: string }>; address: Omit<Address, 'id' | 'is_default'> }
export type OrderList = { items: Order[]; total: number; page: number; page_size: number }

export const shopApi = {
  cart: () => request<Cart>('/api/cart'),
  add: (product_id: string, quantity: number) => mutate<Cart>('/api/cart/items', 'POST', { product_id, quantity }),
  update: (id: string, data: { quantity?: number; selected?: boolean }) => mutate<Cart>(`/api/cart/items/${id}`, 'PATCH', data),
  remove: (id: string) => mutate<void>(`/api/cart/items/${id}`, 'DELETE'),
  addresses: async () => (await request<{ items: Address[] }>('/api/addresses')).items,
  saveAddress: (data: AddressInput, id?: string) => mutate<Address>(id ? `/api/addresses/${id}` : '/api/addresses', id ? 'PATCH' : 'POST', data),
  deleteAddress: (id: string) => mutate<void>(`/api/addresses/${id}`, 'DELETE'),
  checkout: (address_id: string, key: string) => mutate<Order>('/api/orders', 'POST', { address_id }, { 'Idempotency-Key': key }),
  orders: (status = '', page = 1) => request<OrderList>(`/api/orders?${new URLSearchParams({ ...(status ? { status } : {}), page: String(page), page_size: '20' })}`),
  cancel: (id: string) => mutate<Order>(`/api/orders/${id}/cancel`, 'POST'),
  confirmReceipt: (id: string) => mutate<Order>(`/api/orders/${id}/confirm-receipt`, 'POST'),
  order: (id: string) => request<Order>(`/api/orders/${id}`),
  pay: (id: string) => mutate<Order>(`/api/orders/${id}/pay`, 'POST'),
}
