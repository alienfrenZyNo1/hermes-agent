"""Tool schemas for the Phi Memory plugin."""

PHI_MEMORY_SCHEMA = {
    "name": "phi_memory",
    "description": (
        "Inspect or safely clean Hermes built-in MEMORY.md/USER.md using Phi Memory governance. "
        "Semantic compression is proposal-only; mutation requires compress with apply_safe=true."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "status",
                    "review",
                    "compress",
                    "explain",
                    "recall",
                    "dashboard",
                    "meta_status",
                    "meta_rebuild",
                    "meta_validate",
                    "review_due",
                    "schedule",
                    "skill_candidates",
                ],
            },
            "target": {"type": "string", "enum": ["memory", "user"]},
            "text": {"type": "string", "description": "Text to score for explain, or query text for recall."},
            "apply_safe": {"type": "boolean", "description": "For compress only: deterministic safe cleanup with backup."},
            "semantic": {"type": "boolean", "description": "For compress only: return proposal-only semantic compression diff."},
            "budget": {"type": "integer", "description": "Optional semantic proposal character budget."},
            "include_session": {"type": "boolean", "description": "For recall: force session archive fallback."},
            "active_only": {"type": "boolean", "description": "For recall: disable session archive fallback."},
        },
        "required": ["action"],
    },
}
