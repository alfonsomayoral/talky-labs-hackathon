// Text decoding shared by parsers. Bank files (Norma 43) come in ISO-8859-1 / Windows-1252.

const utf8 = new TextDecoder('utf-8', { fatal: true })
let latin1: TextDecoder | null = null

/** UTF-8 when valid (BOM stripped), otherwise Windows-1252. */
export function decodeText(bytes: Uint8Array): string {
  try {
    const text = utf8.decode(bytes)
    return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text
  } catch {
    latin1 ??= new TextDecoder('windows-1252')
    return latin1.decode(bytes)
  }
}

export async function blobText(blob: Blob): Promise<string> {
  return decodeText(new Uint8Array(await blob.arrayBuffer()))
}

/** `"1234.56"`, `"-0.5"`, `"1,234.56"`, `"469994,66"` → integer cents, without float rounding. */
export function decimalToCents(value: string): number {
  let s = value.trim().replace(/\s/g, '')
  if (s.includes(',') && s.includes('.')) s = s.replace(/,/g, '')
  else if (s.includes(',')) s = s.replace(',', '.')
  const negative = s.startsWith('-')
  if (negative || s.startsWith('+')) s = s.slice(1)
  if (!/^\d*(\.\d*)?$/.test(s) || s === '' || s === '.') return Number.NaN
  const [int = '0', frac = ''] = s.split('.')
  const cents = Number(int || '0') * 100 + Number((frac + '00').slice(0, 2))
  return negative ? -cents : cents
}
