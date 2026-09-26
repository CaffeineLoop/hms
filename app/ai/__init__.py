"""Bounded, read-only clinical-analysis assistant (Stage 7).

Layout:
    schemas.py     request / response / validated model-output contracts
    providers.py   configurable LLM provider registry (Gemini via LangChain; deterministic fake)
    tools.py       read-only, patient-bound, permission-gated evidence tools (allowlist)
    guardrails.py  deterministic input and output policy checks
    prompts.py     system prompt and message template
    graph.py       the LangGraph workflow that ties the above together

The assistant never writes: it has no write tools, its tools run inside a READ ONLY database
transaction, and its output is returned to the caller, not stored as a clinical record.
"""
