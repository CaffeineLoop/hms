"""Bounded, read-only clinical-analysis assistant (Stages 7-8).

Layout:
    schemas.py     request / response / validated model-output contracts
    providers.py   configurable LLM provider registry (Gemini / OpenRouter via LangChain; deterministic fake)
    tools.py       read-only, patient-bound, permission-gated evidence tools (allowlist)
    guardrails.py  deterministic input and output policy checks
    prompts.py     system prompt and message template
    graph.py       the LangGraph workflow that ties the above together
    risk_signals.py  Stage 8: deterministic, configurable (demo, NOT validated) potential-risk signals

The assistant never writes: it has no write tools, its tools run inside a READ ONLY database
transaction, and its output is returned to the caller, not stored as a clinical record.
Stage 8: four-day risk analyses are stored by the service (not the graph) in `ai_risk_analyses`,
an AI-suggestion table awaiting human review that is separate from all clinical records.
"""
