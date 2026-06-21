import Image from "next/image";

import { cn } from "@/lib/utils";

/**
 * Brand mark — the orange alpha glyph. Rendered as a rounded white badge so it
 * reads cleanly against the dark canvas. `size` is the rendered edge length in px.
 */
export function Logo({
  size = 16,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <Image
      src="/image.png"
      alt="Alpha Research"
      width={size}
      height={size}
      priority
      className={cn("rounded-md", className)}
    />
  );
}
