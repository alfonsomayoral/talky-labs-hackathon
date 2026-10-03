export const encodePath = (p: string) => p.split('/').map(encodeURIComponent).join('/')

export const absoluteUrl = (url: string) => new URL(url, globalThis.location?.href ?? 'http://localhost/').href

/** JSON from a URL, or null when the endpoint is missing (SPA fallbacks answer HTML with 200). */
export async function fetchJsonOrNull<T>(url: string): Promise<T | null> {
  const res = await fetch(url)
  if (!res.ok || !(res.headers.get('content-type') ?? '').includes('json')) return null
  return (await res.json()) as T
}
