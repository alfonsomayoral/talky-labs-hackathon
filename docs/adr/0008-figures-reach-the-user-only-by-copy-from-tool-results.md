---
status: proposed
---

# Figures reach the user only by copy from tool results, so answers are buffered

The model never types an amount into a card: it calls a local `present` tool that names a stored tool result and the fields to show, and the server copies the values. The finished text passes a number guard (every number must appear in a tool result, a `calculate` result, the knowledge pack or the user's message), a citation validator and a sanitiser before any `delta` is sent. A retracted number cannot be unsent and the app can only append text, so we give up token-by-token streaming and send short, verified answers after the tool rounds, with `status` events in between. We rejected streaming live and checking afterwards (a wrong figure would already be on screen) and relying on the prompt alone (it lowers but does not remove invented figures).
