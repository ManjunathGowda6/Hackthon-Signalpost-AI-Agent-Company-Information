"""Evidence graph for domain-entity matching."""
from dataclasses import dataclass, field

@dataclass
class EvidenceLink:
    link_type: str; source: str; confidence: float; details: str = ""

@dataclass
class EvidenceGraph:
    org_number: str; legal_name: str
    candidates: dict = field(default_factory=dict)
    def add_evidence(self, domain, link):
        self.candidates.setdefault(domain,[]).append(link)
    def get_best_candidate(self):
        if not self.candidates: return None
        best = max(self.candidates.items(), key=lambda x: sum(l.confidence for l in x[1])/len(x[1]))
        score = sum(l.confidence for l in best[1])/len(best[1])
        return (best[0], score) if score >= 0.5 else None
