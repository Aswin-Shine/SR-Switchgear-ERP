import { Modal, type ModalProps } from "./Modal";

export type DialogProps = Omit<ModalProps, "variant">;

/** A centred modal. Reserved for actions that need confirmation or extra input. */
export function Dialog(props: DialogProps) {
  return <Modal {...props} variant="dialog" />;
}
