// Tiny XML reader usable inside Web Workers (no DOMParser there). Enough for the
// well-formed CAMT.053 / Facturae / CFDI files of the datasets: elements, attributes,
// text, CDATA, comments and entities. Namespace prefixes are dropped from `name`.

export interface XmlNode {
  /** Local name (prefix removed). */
  name: string
  attrs: Record<string, string>
  children: XmlNode[]
  text: string
  /** Offsets of the element in the source (for showing the raw node). */
  start: number
  end: number
}

const ENTITIES: Record<string, string> = { lt: '<', gt: '>', amp: '&', quot: '"', apos: "'" }

export function decodeEntities(s: string): string {
  if (!s.includes('&')) return s
  return s.replace(/&(#x[0-9a-fA-F]+|#\d+|[a-zA-Z]+);/g, (m, e: string) => {
    if (e[0] === '#') return String.fromCodePoint(e[1] === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10))
    return ENTITIES[e] ?? m
  })
}

const localName = (qname: string) => qname.slice(qname.indexOf(':') + 1)

/** Index of the `>` closing the tag that starts at `from`, honouring quoted attribute values. */
function tagEnd(src: string, from: number): number {
  let quote = ''
  for (let i = from; i < src.length; i++) {
    const c = src[i]
    if (quote) {
      if (c === quote) quote = ''
    } else if (c === '"' || c === "'") quote = c
    else if (c === '>') return i
  }
  return -1
}

const ATTR = /([^\s=/]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g

export function parseXml(src: string): XmlNode {
  const root: XmlNode = { name: '#document', attrs: {}, children: [], text: '', start: 0, end: src.length }
  const stack: XmlNode[] = [root]
  let i = 0
  while (i < src.length) {
    const lt = src.indexOf('<', i)
    const top = stack[stack.length - 1]
    if (lt === -1) {
      top.text += decodeEntities(src.slice(i))
      break
    }
    if (lt > i) top.text += decodeEntities(src.slice(i, lt))
    if (src.startsWith('<!--', lt)) {
      const e = src.indexOf('-->', lt + 4)
      i = e === -1 ? src.length : e + 3
    } else if (src.startsWith('<![CDATA[', lt)) {
      const e = src.indexOf(']]>', lt + 9)
      top.text += src.slice(lt + 9, e === -1 ? src.length : e)
      i = e === -1 ? src.length : e + 3
    } else if (src[lt + 1] === '?' || src[lt + 1] === '!') {
      const e = tagEnd(src, lt + 1)
      i = e === -1 ? src.length : e + 1
    } else if (src[lt + 1] === '/') {
      const e = src.indexOf('>', lt)
      const name = localName(src.slice(lt + 2, e).trim())
      for (let k = stack.length - 1; k > 0; k--) {
        if (stack[k].name === name) {
          stack[k].end = e + 1
          stack.length = k
          break
        }
      }
      i = e === -1 ? src.length : e + 1
    } else {
      const e = tagEnd(src, lt + 1)
      if (e === -1) throw new Error(`XML mal formado cerca de la posición ${lt}`)
      const selfClosing = src[e - 1] === '/'
      const body = src.slice(lt + 1, selfClosing ? e - 1 : e)
      const nameEnd = body.search(/[\s/]|$/)
      const node: XmlNode = { name: localName(body.slice(0, nameEnd)), attrs: {}, children: [], text: '', start: lt, end: e + 1 }
      for (const m of body.slice(nameEnd).matchAll(ATTR)) node.attrs[localName(m[1])] = decodeEntities(m[2] ?? m[3] ?? '')
      top.children.push(node)
      if (!selfClosing) stack.push(node)
      i = e + 1
    }
  }
  const doc = root.children[0]
  if (!doc) throw new Error('XML sin elemento raíz')
  return doc
}

export const child = (n: XmlNode | null | undefined, name: string) => n?.children.find((c) => c.name === name) ?? null
export const childrenNamed = (n: XmlNode | null | undefined, name: string) => n?.children.filter((c) => c.name === name) ?? []

/** Follows a `A/B/C` path of child names. */
export function at(n: XmlNode | null | undefined, path: string): XmlNode | null {
  let cur: XmlNode | null = n ?? null
  for (const p of path.split('/')) cur = child(cur, p)
  return cur
}

export const textAt = (n: XmlNode | null | undefined, path: string): string | null => {
  const t = at(n, path)?.text.trim()
  return t === undefined || t === '' ? null : t
}

/** All descendants named `name`, depth-first in document order. */
export function descendants(n: XmlNode, name: string, out: XmlNode[] = []): XmlNode[] {
  for (const c of n.children) {
    if (c.name === name) out.push(c)
    descendants(c, name, out)
  }
  return out
}
