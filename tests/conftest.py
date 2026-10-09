"""Test fixtures."""
import pytest
@pytest.fixture
def sample_org(): return "923609016"
@pytest.fixture
def sample_entity():
    return {"organisasjonsnummer":"923609016","navn":"EQUINOR ASA",
            "organisasjonsform":{"kode":"ASA"},"antallAnsatte":21000,
            "forretningsadresse":{"adresse":["Forusbeen 50"],"postnummer":"4035","poststed":"STAVANGER","land":"Norge"},
            "naeringskode1":{"kode":"06.100","beskrivelse":"Utvinning av raaolje"}}
