import { Check, Loader2 } from "lucide-react";

import { Eyebrow } from "@/components/eyebrow";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/lib/types";

/** The research conversation: user prompts and lead-agent responses. */
export function ChatTranscript({ messages }: { messages: ChatMessage[] }) {
  return (
    <ScrollArea className="min-h-0 flex-1">
      <div className="mx-auto flex max-w-3xl flex-col gap-9 px-4 py-8 md:px-6">
        {messages.map((m) => (
          <article key={m.id} className="flex flex-col gap-2.5">
            <Eyebrow>{m.author}</Eyebrow>

            {m.role === "user" ? (
              <div className="self-start rounded-lg border border-hairline bg-canvas-card px-4 py-3 text-[15px] leading-relaxed text-body">
                {m.blocks.map((b, i) => (
                  <p key={i}>{b}</p>
                ))}
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {m.blocks.map((b, i) => (
                  <p
                    key={i}
                    className="text-[15px] leading-relaxed text-body"
                  >
                    {b}
                  </p>
                ))}
                {m.activity &&
                  (() => {
                    const ActivityIcon =
                      m.activity.status === "done" ? Check : Loader2;
                    return (
                      <div className="inline-flex w-fit items-center gap-2 rounded-full border border-hairline px-3 py-1 text-xs text-body">
                        <ActivityIcon
                          className={cn(
                            "size-3.5 text-sunset",
                            m.activity.status === "running" && "animate-spin"
                          )}
                          aria-hidden
                        />
                        {m.activity.label}
                      </div>
                    );
                  })()}
              </div>
            )}
          </article>
        ))}
      </div>
    </ScrollArea>
  );
}
