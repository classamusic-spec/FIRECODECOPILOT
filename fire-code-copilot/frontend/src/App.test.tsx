import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  askStream: vi.fn(),
}));

vi.mock("./lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./lib/api")>();
  return {
    ...actual,
    askStream: apiMocks.askStream,
    getHealth: vi.fn().mockResolvedValue({
      ok: true,
      jurisdiction: "Hartford, Connecticut",
      generation_provider: "local",
      model: "test-model",
    }),
    getCollections: vi.fn().mockResolvedValue({ collections: [] }),
    getModelConfig: vi.fn().mockRejectedValue(new Error("not needed")),
    getRuntimeStatus: vi.fn().mockResolvedValue({ running: false }),
  };
});

async function renderApp(search = "") {
  window.history.replaceState({}, "", `/${search}`);
  vi.resetModules();
  const { default: App } = await import("./App");
  const view = render(<App />);
  await waitFor(() => {
    expect(screen.getByLabelText(/Engine unavailable, test-model/i)).toBeInTheDocument();
  });
  return view;
}

async function submitQuestion(question: string) {
  const user = userEvent.setup();
  const composer = screen.getByRole("textbox", { name: /Ask a code question/i });
  await user.type(composer, question);
  await user.click(screen.getByRole("button", { name: /Send question/i }));
  await waitFor(() => {
    expect(screen.getByRole("button", { name: /Send question/i })).toBeDisabled();
  });
}

describe("App Saved Chats integration", () => {
  beforeEach(() => {
    localStorage.clear();
    apiMocks.askStream.mockReset();
  });

  afterEach(() => {
    cleanup();
    window.history.replaceState({}, "", "/");
  });

  it("writes the question to Saved Chats before generation starts", async () => {
    let storedAtGenerationStart: string | null = null;
    apiMocks.askStream.mockImplementation(async () => {
      storedAtGenerationStart = localStorage.getItem("fcc.threads.v1");
    });
    await renderApp();

    await submitQuestion("Does NFPA 101 section 31.1.1.1 apply?");

    expect(storedAtGenerationStart).not.toBeNull();
    expect(JSON.parse(storedAtGenerationStart ?? "[]")[0].turns[0].text).toBe(
      "Does NFPA 101 section 31.1.1.1 apply?",
    );
  });

  it("never writes showcase questions into real Saved Chats", async () => {
    apiMocks.askStream.mockResolvedValue(undefined);
    await renderApp("?demo=empty");

    await submitQuestion("Synthetic showcase question");

    await waitFor(() => {
      expect(localStorage.getItem("fcc.threads.v1")).toBeNull();
      expect(localStorage.getItem("fcc.activeThread.v1")).toBeNull();
    });
  });
});
