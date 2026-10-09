"""Material change detection."""
MATERIAL = {"legal_identity.legal_name","legal_identity.registration_status",
            "annual_accounts.revenue","leadership_workplaces.roles"}
class ChangeDetector:
    def classify(self, changes):
        for c in changes: c.is_material = any(c.field_path.startswith(m) for m in MATERIAL)
        return changes
