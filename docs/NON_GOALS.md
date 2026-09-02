# NON_GOALS.md — Explicitly not building (and why)

| Not building | Why it wastes time | Revisit when |
|---|---|---|
| Microservices split | One process + DB covers buildathon scale; splitting burns days on plumbing | Real multi-team scale |
| Redis / Celery / Kafka | SKIP LOCKED worker + DB ledger is sufficient and more auditable at our throughput | >~50 cases/sec |
| Vector DB / RAG | No unstructured corpus in this problem; embeddings would be decoration | Merchant knowledge base feature |
| Trained ML risk model | No training data; deterministic score is explainable and defensible | Thousands of labeled real cases |
| Generic chatbot interface | The track demands workflow, not conversation; chat invites prompt-injection surface | Support-agent copilot product |
| Voice / Hinglish IVR agent | Speech+telephony stack is its own hackathon; unverifiable reliability in judging | Post-MVP product idea |
| B2B invoicing / promise-to-pay module | Different domain, no Razorpay API anchor; halves polish of core flow | Separate project |
| Checkout abandonment funnel | Needs frontend instrumentation we lack; overlaps Razorpay Magic Checkout | With merchant storefront data |
| Kubernetes / multi-region | Compose demos perfectly; k8s adds zero judged value here | Production deployment |
| Real SMS/email vendor | Test mode can't deliver anyway; outbox demonstrates intent cleanly | Live deployment contract |
| Refund/dispute flows | Out of track scope; adds money-movement risk without judged upside | Chargeback product |
| Multi-tenant SaaS auth | Single demo merchant suffices; authz complexity isn't judged | Productization |
| Excessive UI polish (animations, mobile) | Judged on workflow clarity, not pixels | After P0–P1 |
| Fake metrics / staged screenshots | Fatal credibility risk; evaluator asks for one replay and it collapses | Never |
| Pretending simulated calls are real | Same category — honesty boundary is a feature (RAZORPAY_INTEGRATION §6) | Never |

Decision heuristic applied to every tempting feature: *does it improve Detect→Recover→Prove, and can a judge verify it in under a minute?* If no, it's a non-goal.
