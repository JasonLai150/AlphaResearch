import type { ReactNode } from "react";

import { Eyebrow } from "@/components/eyebrow";

/** Shared top-of-page heading for the shell pages: eyebrow + title + blurb. */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-hairline px-6 py-6">
      <div className="flex flex-col gap-2">
        {eyebrow ? <Eyebrow as="p">{eyebrow}</Eyebrow> : null}
        <h1 className="text-2xl tracking-[-0.02em] text-ink">{title}</h1>
        {description ? (
          <p className="max-w-2xl text-sm text-mute">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="shrink-0">{actions}</div> : null}
    </div>
  );
}
