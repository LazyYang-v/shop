import { getCsrfToken, notifySessionExpired } from './auth'
import type { Order, OrderList } from './shop'

export type AdminProduct = {
  id: string
  name: string
  category: string
  description: string
  image_url: string
  price: string
  stock: number
  is_listed: boolean
  created_at: string
}
export type ProductInput = Pick<AdminProduct, 'name' | 'category' | 'description' | 'image_url' | 'price' | 'is_listed'>
export type PageResult<T> = { items: T[]; total: number; page: number; page_size: number }
export type InventoryAdjustment = {
  id: string
  product_id: string
  delta: number
  before_stock: number
  after_stock: number
  reason: string
  admin_id: string
  created_at: string
}
export type OrderStatus = 'pending_payment' | 'pending_shipment' | 'pending_receipt' | 'completed' | 'closed'
export type ProductFilters = { q: string; category: string; is_listed: '' | 'true' | 'false' }

// The existing request functions are private. Share their session and CSRF helpers.
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...init, credentials: 'same-origin' })
  if (response.status === 401) notifySessionExpired()
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : null
    const message = typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map((item: { loc?: unknown[]; msg?: string }) => `${item.loc?.slice(1).join('.') || '输入'}：${item.msg || '格式不正确'}`).join('；')
      : response.status === 403 ? '无管理员权限，或安全令牌已失效，请重新登录后重试。' : `请求失败 (${response.status})`
    throw new Error(message)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

async function mutate<T>(path: string, method: 'POST' | 'PATCH', body: unknown): Promise<T> {
  const token = await getCsrfToken()
  return request<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
    body: JSON.stringify(body),
  })
}

const productPath = (id: string) => `/api/admin/products/${encodeURIComponent(id)}`
const orderPath = (id: string) => `/api/admin/orders/${encodeURIComponent(id)}`
const paging = (page: number) => new URLSearchParams({ page: String(page), page_size: '20' })

export const adminApi = {
  products: (filters: ProductFilters, page = 1) => {
    const query = paging(page)
    if (filters.q) query.set('q', filters.q)
    if (filters.category) query.set('category', filters.category)
    if (filters.is_listed) query.set('is_listed', filters.is_listed)
    return request<PageResult<AdminProduct>>(`/api/admin/products?${query}`)
  },
  product: (id: string) => request<AdminProduct>(productPath(id)),
  createProduct: (input: ProductInput) => mutate<AdminProduct>('/api/admin/products', 'POST', input),
  updateProduct: (id: string, input: Partial<ProductInput>) => mutate<AdminProduct>(productPath(id), 'PATCH', input),
  adjustments: (id: string, page = 1) => request<PageResult<InventoryAdjustment>>(`${productPath(id)}/inventory-adjustments?${paging(page)}`),
  adjustInventory: (id: string, delta: number, reason: string) => mutate<InventoryAdjustment>(`${productPath(id)}/inventory-adjustments`, 'POST', { delta, reason }),
  orders: (status: OrderStatus | '', page = 1) => {
    const query = paging(page)
    if (status) query.set('status', status)
    return request<OrderList>(`/api/admin/orders?${query}`)
  },
  order: (id: string) => request<Order>(orderPath(id)),
  ship: (id: string, shipping_company: string, tracking_number: string) => mutate<Order>(`${orderPath(id)}/ship`, 'POST', { shipping_company, tracking_number }),
}
