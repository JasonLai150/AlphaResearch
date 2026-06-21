import * as React from "react";

import { cn } from "@/lib/utils";

/* text-input — canvas-soft fill, hairline border, rounded.sm (8px). */
const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "flex h-10 w-full rounded-lg border border-hairline bg-canvas-soft px-4 py-2 text-base text-ink transition-colors placeholder:text-mute focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Input.displayName = "Input";

export { Input };
