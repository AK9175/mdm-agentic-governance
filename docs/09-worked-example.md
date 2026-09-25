# 9. Worked example: bracket rev B → rev C

A single scenario that exercises the whole system. All values are synthetic.

## The change

An engineer drafts change **ECN-2291** in the PLM: bracket **BRK-10442** moves
from **rev B to rev C**, switching material from **aluminum (AMS 4027)** to
**titanium (AMS 4911)**. It is still a **draft** — nothing approved or synced yet.

Crosswalk: `BRK-10442` = ERP material `50010442` = MES part `BRK-10442`.

## Step by step

**1. Trigger.** The draft-change event hits the event bus. The supervisor opens
a case.

**2. Route.** `change_drafted` is a known event → routed by rule to **Change
Impact** and **Data Quality**, in parallel. No LLM call for routing.

**3. Change Impact** asks "what depends on rev B?" and finds:
- `erp.get_stock` → **40 EA** rev B in plant 1000
- `erp.get_open_pos` → **PO 4500018832**, 60 EA, due in 3 weeks
- `mes.get_open_work_orders` → **WO-7781, WO-7782, WO-7790** on rev B
- `mes.get_process_plan` → machining steps written for **aluminum**
- `plm.where_used` → used in **ASM-2201, ASM-2240**

Finding: an immediate switch wastes 40 + 60 brackets; 3 work orders are mid-build;
instructions need review for titanium.

**4. Data Quality** dry-runs rev C:
- `pipeline.dry_run(target=ERP)` → **FAIL**: no material group for AMS 4911
- `pipeline.dry_run(target=MES)` → **PASS**
- `pipeline.pending_messages` → nothing stuck
- `mapping.find_similar("AMS 4911")` → suggests **MG-TI64** (used for titanium bar)

Finding: ERP would reject rev C on a missing mapping; the fix is one new mapping
row.

### The dry-run in detail

The engineer changed one attribute: material spec AMS 4027 → AMS 4911. The
integration translates a PLM spec into an SAP **material group** (`MATKL`) via a
lookup table. No row exists for titanium sheet, so a real sync would fail on a
required field. The dry run runs *the same mapping logic* against the draft, so
the gap surfaces **before** release. Fixing one row also protects every future
titanium part.

**5. Proposal + policy.** The supervisor merges both agents' findings into one
proposal:

| Action | Risk |
|---|---|
| Add mapping `AMS 4911 → MG-TI64` | medium |
| Start rev C after WO-7790 finishes (effectivity) | high |
| Cancel PO 4500018832 (60 rev B) | high |

Highest risk is high → the whole proposal goes to the **change board**.

**6. Approval (interrupt).** The graph pauses with full state saved; it can wait
days for the board.

**7. Gateway.** On approval, the gateway applies all three actions with
idempotency keys (`ECN-2291-A1/A2/A3`) and audit records. ECN-2291 can now be
released and syncs cleanly on the first attempt. (On rejection, nothing is
written, and the decision is saved as an eval example.)

## Why this is "proactive"

- **Reactive world:** ECN approved → released → SAP sync fails on the missing
  mapping → someone discovers 40 rev B units are now obsolete, possibly after
  rev C is already on order.
- **Agent world:** both problems surface while the ECN is a draft → the board
  approves a change that already has a stock plan and a working mapping.

**The value isn't fixing failures faster — it's that the failure never happens.**

## The two agents' outputs, in plain language

**Change Impact:**
> Switching the bracket from aluminum to titanium affects parts we already have:
> 40 in the warehouse, 60 more on order, and 3 being built right now. Switching
> immediately wastes them and leaves the shop-floor instructions wrong for the
> new metal. Recommendation: use up the old brackets, cancel the extra order, and
> start titanium after the current jobs finish.

**Data Quality:**
> If approved as-is, purchasing and shop-floor systems won't accept the new
> titanium bracket, because titanium was never set up in those systems and a few
> required details are missing. Recommendation: add the titanium setup now (a
> one-time fix) so the change goes through smoothly on approval.

## Two other scenarios (in the prototype)

- **Duplicate part:** a new titanium bracket is requested in the ERP at another
  plant; Entity Resolver finds it already exists as BRK-10442 rev C and proposes
  reuse + plant extension instead of a new material.
- **Failed sync:** a MES→ERP posting fails on an undefined unit (KG); Data
  Quality finds the root cause and blast radius, and flags two more materials
  with the same gap; the low-risk fix auto-executes.
