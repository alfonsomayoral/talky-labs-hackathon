// File inputs styled as buttons, and a drop zone that hands over dropped files (folders included).
import { useRef, useState, type DragEvent, type ReactNode } from 'react'
import clsx from 'clsx'
import { buttonClassName, type ButtonVariant } from '@/components'
import { filesFromDataTransfer } from '@/data/stores'
import s from './FilePickers.module.css'

interface PickerProps {
  children: ReactNode
  icon?: ReactNode
  variant?: ButtonVariant
  disabled?: boolean
  onFiles: (files: File[]) => void
}

function Picker({ children, icon, variant = 'secondary', disabled, onFiles, directory, accept, multiple }: PickerProps & { directory?: boolean; accept?: string; multiple?: boolean }) {
  return (
    <label className={clsx(buttonClassName({ variant, size: 'sm' }), s.picker, disabled && s.disabled)} aria-disabled={disabled || undefined}>
      {icon}
      <span>{children}</span>
      <input
        type="file"
        hidden
        disabled={disabled}
        accept={accept}
        multiple={multiple || directory}
        ref={(el) => {
          if (el && directory) el.webkitdirectory = true
        }}
        onChange={(e) => {
          const files = [...(e.target.files ?? [])]
          e.target.value = ''
          if (files.length) onFiles(files)
        }}
      />
    </label>
  )
}

export const FolderPicker = (props: PickerProps) => <Picker {...props} directory />
export const ZipPicker = (props: PickerProps) => <Picker {...props} accept=".zip,application/zip" />
export const FilesPicker = (props: PickerProps & { accept?: string }) => <Picker {...props} multiple />

export const isSingleZip = (files: File[]) => files.length === 1 && files[0].name.toLowerCase().endsWith('.zip')

export function DropZone({ onFiles, disabled, children, className }: { onFiles: (files: Promise<File[]>) => void; disabled?: boolean; children: ReactNode; className?: string }) {
  const [over, setOver] = useState(false)
  const depth = useRef(0)
  const reset = () => {
    depth.current = 0
    setOver(false)
  }
  return (
    <div
      className={clsx(s.drop, over && s.over, disabled && s.disabled, className)}
      onDragEnter={(e) => {
        e.preventDefault()
        depth.current++
        if (!disabled) setOver(true)
      }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={() => {
        depth.current = Math.max(0, depth.current - 1)
        if (depth.current === 0) setOver(false)
      }}
      onDrop={(e: DragEvent) => {
        e.preventDefault()
        reset()
        if (disabled) return
        // Must run synchronously inside the drop handler: the DataTransfer is emptied afterwards.
        onFiles(filesFromDataTransfer(e.dataTransfer))
      }}
    >
      {children}
    </div>
  )
}
