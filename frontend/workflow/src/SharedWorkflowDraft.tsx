import { createContext, useContext, type ReactNode } from "react";
import { useSharedWorkflowDraft } from "./useSharedWorkflowDraft";

const SharedDraftContext = createContext<ReturnType<typeof useSharedWorkflowDraft> | null>(null);

/** Keep pending edits alive when the user visits the question bank, KB or run history. */
export function SharedWorkflowDraftProvider({children}: {children: ReactNode}) {
  const draft = useSharedWorkflowDraft();
  return <SharedDraftContext.Provider value={draft}>{children}</SharedDraftContext.Provider>;
}

export function useWorkflowDraft() {
  const draft = useContext(SharedDraftContext);
  if (!draft) throw new Error("SharedWorkflowDraftProvider is required");
  return draft;
}
