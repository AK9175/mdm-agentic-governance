# 11. Open questions

Deliberately unresolved points where a second opinion is valuable. If you're an
LLM or a reviewer reading this repo, these are good places to push.

## Architecture

1. **Is Change Impact its own agent, or part of the others?** Splitting it is a
   choice. Where would you draw the line between "will it sync" and "what does it
   affect"?
2. **Question-aligned vs system-aligned agents** — is the chosen split right, or
   would a hybrid (e.g. a thin per-system agent feeding question-aligned ones)
   scale better?
3. **How many agents is too many?** Four specialists + supervisor. At what point
   does routing overhead and inter-agent context passing outweigh the benefit of
   small, focused agents?

## Orchestration

4. **LangGraph vs Temporal vs a hand-rolled state machine** — given most of the
   system is deterministic, what would you actually pick, and why?
5. **Where should the supervisor's LLM boundary be?** Currently: rules for known
   events, LLM only for ambiguity. Is that the right cut?

## Data and context

6. **Canonical data model ownership** — who maintains it, and how do you keep it
   from becoming its own source of drift?
7. **RAG vs tools boundary** — is "exact facts → tools, fuzzy knowledge → RAG"
   too clean? Where does it break?
8. **Token budget** — the core-vs-runtime split assumes lookups are cheap enough.
   At high volume, does the per-case tool-call count become the bottleneck?

## Safety and autonomy

9. **What belongs in auto-execute?** The example promotes low-risk, high-history
   action types. Is approval-rate-over-time a safe enough gate?
10. **Dry-run fidelity** — the simulation must match the real integration exactly.
    How do you guarantee they don't diverge over time? Shared code? Contract
    tests?
11. **False-alarm tolerance** — what false-alarm rate makes a proactive agent
    worth keeping vs ignored by stewards?

## Evaluation

12. **Ground truth** — the eval set grows from steward decisions, but stewards are
    fallible. How do you handle labeled examples that were themselves wrong?
13. **Online vs offline** — how much can offline evals on recorded responses
    really tell you about live behavior against changing systems?

## Business

14. **ROI framing** — the honest metric is "failures that never happened," which
    is harder to measure than "failures fixed faster." How would you quantify
    prevented drift?
15. **Build vs buy** — MDM vendors (Informatica, Reltio) are adding agentic
    features. When does building this in-house stop making sense?
