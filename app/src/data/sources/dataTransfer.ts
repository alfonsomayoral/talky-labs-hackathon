// Drag & drop of folders. Entries must be taken synchronously inside the drop handler,
// so call this directly from onDrop (it reads dt.items before the first await).

const readAll = (reader: FileSystemDirectoryReader) =>
  new Promise<FileSystemEntry[]>((ok, ko) => {
    const all: FileSystemEntry[] = []
    const next = () =>
      reader.readEntries((batch) => {
        if (!batch.length) return ok(all)
        all.push(...batch)
        next()
      }, ko)
    next()
  })

const fileOf = (entry: FileSystemFileEntry) => new Promise<File>((ok, ko) => entry.file(ok, ko))

/** Files carry their path (without leading slash) in `webkitRelativePath`, like a webkitdirectory input. */
export async function filesFromDataTransfer(dt: DataTransfer): Promise<File[]> {
  const entries = [...dt.items].map((i) => (i.kind === 'file' ? i.webkitGetAsEntry() : null)).filter((e): e is FileSystemEntry => !!e)
  const loose = entries.length ? [] : [...dt.files]
  const out: File[] = []
  const walk = async (entry: FileSystemEntry): Promise<void> => {
    if (entry.isDirectory) {
      for (const child of await readAll((entry as FileSystemDirectoryEntry).createReader())) await walk(child)
    } else if (entry.isFile) {
      const file = await fileOf(entry as FileSystemFileEntry)
      Object.defineProperty(file, 'webkitRelativePath', { value: entry.fullPath.replace(/^\/+/, ''), configurable: true })
      out.push(file)
    }
  }
  for (const e of entries) await walk(e)
  return [...out, ...loose]
}
