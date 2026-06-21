import type { ElementType, ReactNode } from "react";

import { cn } from "@/lib/utils";

/*
  The brand's signature label: GeistMono, UPPERCASE, positive tracking — reads
  like a code comment above each section. See DESIGN.md `eyebrow-mono` /
  `caption-mono-sm` (12px / 1.2px tracking). Pass `as` to render section labels
  as real headings (h2/h3) so the document has an accessible outline.
*/
export function Eyebrow({
  as: Tag = "span",
  className,
  children,
}: {
  as?: ElementType;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Tag
      className={cn(
        "font-mono text-[12px] uppercase tracking-[0.1em] text-mute",
        className
      )}
    >
      {children}
    </Tag>
  );
}
