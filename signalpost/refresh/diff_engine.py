"""Snapshot diff engine."""
from signalpost.models.refresh import FieldChange

class DiffEngine:
    def diff(self, previous, current, path=""):
        changes = []
        for key in set(list(previous.keys())+list(current.keys())):
            fp = f"{path}.{key}" if path else key
            pv, cv = previous.get(key), current.get(key)
            if pv is None and cv is not None:
                changes.append(FieldChange(field_path=fp, current_value=cv, change_type="added"))
            elif pv is not None and cv is None:
                changes.append(FieldChange(field_path=fp, previous_value=pv, change_type="removed"))
            elif isinstance(pv,dict) and isinstance(cv,dict):
                changes.extend(self.diff(pv, cv, fp))
            elif pv != cv:
                changes.append(FieldChange(field_path=fp, previous_value=pv, current_value=cv, change_type="modified"))
        return changes
