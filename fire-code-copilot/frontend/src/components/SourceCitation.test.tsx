import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import SourceCitation from "./SourceCitation";

afterEach(() => {
  document.body.style.overflow = "";
});

describe("SourceCitation page viewer", () => {
  it("opens the typeset page in an enlarged, zoomable dialog and closes with Escape", async () => {
    const user = userEvent.setup();
    render(
      <SourceCitation
        index={1}
        source={{
          text: "31.1.1.1 The provisions of this chapter shall apply.",
          metadata: {
            source: "NFPA 101  2021/Chapter 31.pdf",
            book: "NFPA 101",
            edition: "2021",
            section: "31.1.1.1",
            page: 2,
          },
        }}
      />,
    );

    await user.click(screen.getByRole("button", { name: /NFPA 101 2021/i }));
    await user.click(screen.getByRole("button", { name: /View page 2 in the book/i }));
    await user.click(screen.getByRole("button", { name: /Expand NFPA 101 page 2/i }));

    const dialog = screen.getByRole("dialog", { name: /Enlarged NFPA 101 page 2/i });
    expect(dialog).toBeInTheDocument();
    expect(document.body).toHaveStyle({ overflow: "hidden" });
    expect(screen.getByText("100%")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Zoom in/i }));
    expect(screen.getByText("125%")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.body).not.toHaveStyle({ overflow: "hidden" });
  });
});
