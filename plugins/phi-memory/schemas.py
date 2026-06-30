"""Tool schemas for the Phi Memory plugin."""

PHI_MEMORY_SCHEMA = {
    "name": "phi_memory",
    "description": (
        "Inspect or safely clean Hermes built-in MEMORY.md/USER.md using Phi Memory governance. "
        "Actions status/review/compress are dry-run unless action=compress with apply_safe=true."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "review", "compress", "explain", "recall"],
                "description": "Phi Memory action to run.",
            },
            "target": {
                "type": "string",
                "enum": ["memory", "user"],
                "description": "Built-in memory file to inspect: MEMORY.md or USER.md.",
            },
            "text": {
                "type": "string",
                "description": "Text to score for explain, or query text for recall.",
            },
            "apply_safe": {
                "type": "boolean",
                "description": "For compress only: apply deterministic safe cleanup with a backup. No semantic rewrite.",
            },
        },
        "required": ["action"],
    },
}
