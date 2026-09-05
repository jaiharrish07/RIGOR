# Prompt exploration notes

## Transformer paper abstract (Attention Is All You Need)
- Extracted both BLEU claims correctly (28.4 EN-DE, 41.8 EN-FR), with accurate verbatim evidence quotes.
- Also extracted "3.5 days on eight GPUs" as a third claim with metric_name "training time". Debatable
  whether this should count as a *performance* claim vs. a *cost/efficiency* claim — the prompt didn't
  distinguish, so the model treated any quantitative result as fair game.
- No hallucinated claims and no invented dataset names in this run — abstract was information-dense and
  explicit, which likely helped. Worth testing against a vaguer abstract to see if that holds.
- Third claim's dataset field duplicated "WMT 2014 English-to-French translation task" from the second
  claim, since both numbers came from the same sentence — the model didn't distinguish "this is the same
  dataset as the claim above" from "this is a separate claim." Might want a merge/parent-claim relationship
  in the schema for Week 3.

## Ideas for Week 3
- Need an explicit instruction distinguishing "performance metric" (accuracy, BLEU, F1, IoU) from
  "efficiency/cost metric" (training time, GPU-hours, parameter count) — decide whether both belong in
  the same claims list or need separate categories.
- Consider: "if dataset name is not stated, mark as 'unknown', don't guess" — didn't trigger in this run
  since the paper was explicit, but should stress-test on a paper with vaguer wording ("the standard benchmark").
- Consider a few-shot example in the system prompt to standardize what counts as a "claim" boundary.
- Test on a second paper with weaker/vaguer language to see failure modes this abstract didn't expose.