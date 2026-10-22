export type Product = {
  id: string
  name: string
  category: string
  description: string
  image_url: string
  price: string
  stock: number
}

export type ProductList = {
  items: Product[]
  total: number
  page: number
  page_size: number
}

export type ProductQuery = { q?: string; category?: string; sort?: 'popular' | 'price_asc' | 'price_desc'; page?: number; page_size?: number }

export async function getCategories(): Promise<string[]> {
  const response = await fetch('/api/categories')
  if (!response.ok) throw new Error(`分类加载失败 (${response.status})`)
  const body = await response.json() as { items: string[] }
  return body.items
}

export async function getProducts(query: ProductQuery = {}): Promise<ProductList> {
  const params = new URLSearchParams()
  Object.entries(query).forEach(([key, value]) => { if (value !== undefined && value !== '') params.set(key, String(value)) })
  const response = await fetch(`/api/products?${params.toString()}`)
  if (!response.ok) throw new Error(`商品加载失败 (${response.status})`)
  return response.json() as Promise<ProductList>
}

export async function getProduct(id: string): Promise<Product> {
  const response = await fetch(`/api/products/${id}`)
  if (!response.ok) throw new Error(`商品详情加载失败 (${response.status})`)
  return response.json() as Promise<Product>
}
