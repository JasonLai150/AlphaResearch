"use client";

import { Toaster as SonnerToaster } from "sonner";

type ToasterProps = React.ComponentProps<typeof SonnerToaster>;

function Toaster({ ...props }: ToasterProps) {
  return (
    <SonnerToaster
      theme="dark"
      richColors
      position="bottom-right"
      closeButton
      toastOptions={{
        classNames: {
          toast:
            "group rounded-lg border border-hairline bg-canvas-card text-ink shadow-lg",
          title: "text-sm text-ink",
          description: "text-xs text-mute",
          actionButton:
            "rounded-md bg-primary px-2 py-1 text-xs text-primary-foreground",
          cancelButton:
            "rounded-md bg-canvas-soft px-2 py-1 text-xs text-body",
          closeButton: "border-hairline bg-canvas-soft text-mute",
        },
      }}
      {...props}
    />
  );
}

export { Toaster };
