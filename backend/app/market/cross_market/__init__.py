"""Backend-owned cross-market relation, evidence, and context contracts."""

# Keep package initialization import-free: adr_parity consumes relation_store,
# while context consumes adr_parity.  Public callers import the owning module
# explicitly so this package boundary cannot introduce an import cycle.
