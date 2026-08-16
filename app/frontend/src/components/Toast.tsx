import { useEffect, useState } from "react";

export interface ToastState {
  message: string;
  kind: "ok" | "bad";
  id: number;
}

export function Toast({ toast }: { toast: ToastState | null }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!toast) return;
    setVisible(true);
    const id = setTimeout(() => setVisible(false), 3400);
    return () => clearTimeout(id);
  }, [toast]);

  if (!toast) return null;
  return <div className={"toast " + (visible ? "show " : "") + toast.kind}>{toast.message}</div>;
}
