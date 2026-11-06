import { Overlay, type OverlayProps } from './Overlay'

export function Drawer(props: Omit<OverlayProps, 'variant'>) {
  return <Overlay {...props} variant="drawer" />
}
