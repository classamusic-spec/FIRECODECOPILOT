import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Turn } from "./types";
import { loadThreads, saveStartedThread } from "./threads";

describe("Saved Chats persistence", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.spyOn(Date, "now").mockReturnValue(1_787_200_000_000);
  });

  it("persists the user's question as soon as a chat starts, before the answer finishes", () => {
    const userTurn: Turn = {
      id: "user-1",
      role: "user",
      text: "Does NFPA 101 section 31.1.1.1 apply?",
      buildingContext: "Existing apartment building",
    };

    const next = saveStartedThread([], "thread-1", [], userTurn);
    const stored = loadThreads();

    expect(next).toHaveLength(1);
    expect(stored).toHaveLength(1);
    expect(stored[0]).toMatchObject({
      id: "thread-1",
      title: "Does NFPA 101 section 31.1.1.1 apply?",
      turns: [userTurn],
    });
  });
});
