import { Modal, type ModalProps } from "./Modal";

export type DrawerProps = Omit<ModalProps, "variant">;

/** A right-hand panel for detail that would otherwise cost a page navigation. */
export function Drawer(props: DrawerProps) {
  return <Modal {...props} variant="drawer" />;
}
