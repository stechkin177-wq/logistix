import { Overlay, type OverlayProps } from './Overlay'

export function Dialog(props: Omit<OverlayProps, 'variant'>) {
  return <Overlay {...props} variant="dialog" />
}
