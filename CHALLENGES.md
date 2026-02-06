# Challenges & Notes: Historical Subscription Pricing Collection

## Overview

This document describes deviations from the protocol, assumptions made during implementation, and challenges encountered while collecting historical subscription pricing data.

---

## Challenges

### 1. **Multiple Pricing Pages**
**Deviation:** Some websites may have multiple subscription products

- Ex: On 'https://www.cnn.com/subscription', it has subscription for 'All Access' and 'Basic'. How do I identify the subscription type and pair it with its price
- Possible solution:
    - Use LLM image model for help?

---

### 2. **Pricing Type Inference**
**Deviation:** Handle ambiguity with context-dependent pricing.

**Resolution:** Two-stage extraction:

**Stage A: Explicit Markers** (High Confidence)
- Only extract prices with explicit unit: `$99/month`, `€59.99/year`
- Direct assignment: Unit text → typing (monthly/annual/weekly/daily)
- No assumption needed

**Stage B: Contextual Inference** (Medium Confidence)
- For standalone prices (e.g., `$99`), scan 140-char context window
- Match to closest semantic cue (distance metric)
- If "annual" cue within 120 chars → force type="annual"
- Otherwise → type="unknown" if ambiguous

**Assumptions:**
- Cue proximity correlates with intent (prices near "annual" are annual prices)
- 140-char window captures relevant context for typical HTML layouts
- If multiple cues equidistant → type="unknown" (conservative)

**Limitation:** Cannot reliably distinguish trial pricing, discounts, or bundle pricing (print+digital) from regular monthly/annual. 



