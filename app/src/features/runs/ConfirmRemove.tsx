// Confirmation before removing a dataset or a run from this browser: it cannot be undone.
import { Button, Dialog } from '@/components'

export interface RemoveTarget {
  title: string
  description: string
  run(): Promise<void>
}

export function ConfirmRemove({ target, onClose }: { target: RemoveTarget | null; onClose: () => void }) {
  return (
    <Dialog
      open={target !== null}
      onClose={onClose}
      size="sm"
      title={target?.title ?? ''}
      description={target?.description}
      footer={
        <>
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="danger"
            onClick={() => {
              onClose()
              void target?.run()
            }}
          >
            Eliminar
          </Button>
        </>
      }
    />
  )
}
