import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ChatComposer } from "@/components/chat-composer";

afterEach(() => {
  cleanup();
});

describe("ChatComposer", () => {
  it("submits on Enter with the trimmed text", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<ChatComposer onSubmit={onSubmit} />);

    const textarea = screen.getByRole("textbox");
    await user.type(textarea, "  hello world  ");
    await user.keyboard("{Enter}");

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith("hello world");
  });

  it("inserts a newline on Shift+Enter and does not submit", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<ChatComposer onSubmit={onSubmit} />);

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    await user.type(textarea, "line one");
    await user.keyboard("{Shift>}{Enter}{/Shift}");
    await user.type(textarea, "line two");

    expect(onSubmit).not.toHaveBeenCalled();
    expect(textarea.value).toBe("line one\nline two");
  });

  it("does not submit empty or whitespace-only input", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<ChatComposer onSubmit={onSubmit} />);

    const textarea = screen.getByRole("textbox");

    // Empty: pressing Enter with nothing typed.
    await user.click(textarea);
    await user.keyboard("{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();

    // Whitespace-only: spaces then Enter.
    await user.type(textarea, "    ");
    await user.keyboard("{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("restores the typed text and stays enabled when onSubmit rejects", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockRejectedValue(new Error("boom"));
    render(<ChatComposer onSubmit={onSubmit} />);

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    await user.type(textarea, "needs retry");
    await user.keyboard("{Enter}");

    expect(onSubmit).toHaveBeenCalledWith("needs retry");

    // After the rejection settles, the text is restored...
    await waitFor(() => {
      expect(textarea.value).toBe("needs retry");
    });
    // ...and the textarea is not left disabled.
    expect(textarea).not.toBeDisabled();
  });
});
