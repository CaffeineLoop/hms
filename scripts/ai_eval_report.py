"""Render the Stage 9 adversarial evaluation summary (Markdown) from pytest result JSON.

    HMS_AI_EVAL_REPORT=reports/ai_eval.json pytest tests/unit/test_ai_adversarial_guardrails.py
    HMS_AI_EVAL_REPORT=reports/ai_eval.json pytest tests/integration/test_ai_adversarial_api.py
    python scripts/ai_eval_report.py reports/ai_eval.json [--baseline pre_fix.json] > summary.md

Counting: every tagged case is one test. "Blocked" = BLOCKED cases that passed (the attack was
refused/rejected/denied); "Bounded" = BOUNDED cases that passed (accepted but kept inside the
boundary); "Controls" = ALLOWED benign cases that passed (not over-blocked); "Known limitation" =
strict xfail cases documenting attacks the deterministic guardrails do not catch.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.adversarial import CATEGORIES  # noqa: E402


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def summarize(results: dict) -> tuple[dict, Counter]:
    per_category: dict[str, Counter] = defaultdict(Counter)
    totals: Counter = Counter()
    for r in results.values():
        c = per_category[r["category"]]
        for bucket in (c, totals):
            bucket["total"] += 1
            bucket[r["outcome"]] += 1
            if r["outcome"] == "passed":
                bucket[{"BLOCKED": "blocked", "BOUNDED": "bounded", "ALLOWED": "controls"}[r["expect"]]] += 1
    return per_category, totals


def render(results: dict, baseline: dict | None, versions: dict) -> str:
    per_category, totals = summarize(results)
    lines = ["## Adversarial evaluation results", "",
             f"Model under test: deterministic fake/attacker models (automated); live provider "
             f"`{versions['provider']}` / `{versions['model']}` verified manually. "
             f"Guardrail policy `{versions['guardrail']}`, prompt fingerprint `{versions['prompt']}`.", "",
             f"**Total {totals['total']} | passed {totals['passed']} | failed {totals['failed']} | "
             f"blocked {totals['blocked']} | bounded {totals['bounded']} | controls {totals['controls']} | "
             f"known limitations (strict xfail) {totals['xfailed']}**", "",
             "| Category | Total | Passed | Failed | Blocked | Bounded | Controls | Known limitation |",
             "|---|---|---|---|---|---|---|---|"]
    for key, label in CATEGORIES.items():
        c = per_category.get(key, Counter())
        lines.append(f"| {label} | {c['total']} | {c['passed']} | {c['failed']} | {c['blocked']} | {c['bounded']} | "
                     f"{c['controls']} | {c['xfailed']} |")
    failures = [r for r in results.values() if r["outcome"] == "failed"]
    lines += ["", "### Failures", ""]
    lines += [f"- `{r['test']}` ({r['category']}): {r['reason']}" for r in failures] or ["None."]
    limits = [r for r in results.values() if r["outcome"] == "xfailed"]
    lines += ["", "### Known limitations (documented by strict xfail tests)", ""]
    lines += [f"- `{r['test']}`: {r['limitation']}" for r in limits] or ["None."]
    if baseline:
        _, before = summarize(baseline)
        lines += ["", "### Pre-fix baseline", "",
                  f"Baseline run(s) before the Stage 9 fixes: **{before['failed']} failures out of "
                  f"{before['total']}** cases.", ""]
        by_cat = Counter(r["category"] for r in baseline.values() if r["outcome"] == "failed")
        lines += [f"- {CATEGORIES[k]}: {n} failing" for k, n in sorted(by_cat.items())]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results")
    parser.add_argument("--baseline", action="append", default=[])
    args = parser.parse_args()
    from app.ai.guardrails import GUARDRAIL_VERSION
    from app.ai.prompts import PROMPT_VERSION
    from app.core.config import Settings

    fields = Settings.model_fields
    versions = {"guardrail": GUARDRAIL_VERSION, "prompt": PROMPT_VERSION,
                "provider": fields["llm_provider"].default, "model": fields["llm_model"].default}
    baseline = {}
    for path in args.baseline:
        baseline.update(load(path))
    sys.stdout.write(render(load(args.results), baseline or None, versions))


if __name__ == "__main__":
    main()
