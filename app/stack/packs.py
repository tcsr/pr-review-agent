from __future__ import annotations

BUILTIN_PACKS: dict[str, list[str]] = {
    "angular": [
        "Use OnPush change detection where possible.",
        "Unsubscribe from observables (takeUntil/async pipe) to avoid leaks.",
        "Keep logic out of templates.",
    ],
    "react": [
        "Verify hook dependency arrays are correct and complete.",
        "Avoid inline object/array props that force child re-renders.",
        "Ensure list items have stable keys.",
    ],
    "nextjs": [
        "Respect server vs client component boundaries ('use client').",
        "Use appropriate data-fetching patterns; avoid client fetch for static data.",
    ],
    "nestjs": [
        "Validate DTOs at boundaries.",
        "Respect module boundaries and injectable scopes.",
    ],
    "node": [
        "Handle async errors; avoid unhandled promise rejections.",
        "Avoid blocking synchronous calls on the event loop.",
    ],
    "java": [
        "Guard against nulls; prefer Optional at boundaries.",
        "Close resources with try-with-resources.",
    ],
    "python": [
        "Add type hints to new public functions.",
        "Avoid mutable default arguments.",
        "Use context managers for resource handling.",
    ],
    "javascript": [
        "No leftover console.log/debugger.",
        "Prefer const/let over var.",
    ],
    "typescript": [
        "Avoid `any`; prefer precise types.",
        "No leftover console.log/debugger.",
    ],
    "css": [
        "Avoid !important and overly specific selectors.",
        "Use responsive units over fixed pixels where appropriate.",
    ],
}


def pack_criteria(stacks: set[str], stacks_cfg) -> list[str]:
    out: list[str] = []
    for stack, criteria in BUILTIN_PACKS.items():
        if stack in stacks and stacks_cfg.packs.get(stack) is not False:
            out.extend(criteria)
    return out
