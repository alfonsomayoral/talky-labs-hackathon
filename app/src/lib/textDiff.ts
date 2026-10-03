// Which part of a value differs from a reference (look-alike domains, a changed IBAN digit).
/** Splits `text` around what differs from `reference`: the common start, the changed middle and the common end. */
export function textDiff(text: string, reference: string): { before: string; changed: string; after: string } {
  let start = 0
  while (start < text.length && start < reference.length && text[start] === reference[start]) start++
  let end = 0
  while (end < text.length - start && end < reference.length - start && text[text.length - 1 - end] === reference[reference.length - 1 - end]) end++
  return { before: text.slice(0, start), changed: text.slice(start, text.length - end), after: text.slice(text.length - end) }
}
