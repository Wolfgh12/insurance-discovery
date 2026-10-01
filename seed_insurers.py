import os
import sys
from pathlib import Path

# Dynamically resolve project root containing 'core'
CURRENT_DIR = Path(__file__).resolve().parent
if (CURRENT_DIR / "core").exists():
    BASE_DIR = CURRENT_DIR
elif (CURRENT_DIR.parent / "core").exists():
    BASE_DIR = CURRENT_DIR.parent
else:
    BASE_DIR = CURRENT_DIR

sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.local')

import django
django.setup()

from django.db import models
from django.db.models import ProtectedError, Q
from vault.models import InsuranceCompany, PolicyRecord

# 1. Cleanly reset or neutralize existing insurers to prevent unique constraint collisions
try:
    InsuranceCompany.objects.all().delete()
    print("Cleaned up existing insurer records.")
except ProtectedError:
    print("Policies linked to existing insurers detected. Neutralizing fields to avoid unique constraint collisions...")
    for comp in InsuranceCompany.objects.all():
        comp.license_number = f"TMP_LIC_{comp.id}"
        comp.name = f"__TMP_{comp.id}_{comp.name}"[:250]
        comp.slug = f"tmp-{comp.id}-{comp.slug}"[:50]
        comp.save(update_fields=['license_number', 'name', 'slug'])

# 2. National Insurance Commission (NIC) Licensed Insurers Directory (26 Verified Institutions)
comprehensive_insurers = [
    # --- Life Assurance Underwriters ---
    {
        "name": "GLICO Life Assurance",
        "slug": "glico-life",
        "license_number": "NIC/LF/004",
        "contact_email": "customerservices@glicogroup.com",
        "claims_hotline": "+233 30 221 8500",
        "is_verified": True
    },
    {
        "name": "Enterprise Life Assurance",
        "slug": "enterprise-life",
        "license_number": "NIC/LF/001",
        "contact_email": "info.life@enterprisegroup.com.gh",
        "claims_hotline": "+233 30 263 4777",
        "is_verified": True
    },
    {
        "name": "SIC Life Company",
        "slug": "sic-life",
        "license_number": "NIC/LF/002",
        "contact_email": "enquiries@siclife.com.gh",
        "claims_hotline": "+233 30 274 2450",
        "is_verified": True
    },
    {
        "name": "StarLife Assurance",
        "slug": "starlife-assurance",
        "license_number": "NIC/LF/003",
        "contact_email": "info@starlife.com.gh",
        "claims_hotline": "+233 30 273 9300",
        "is_verified": True
    },
    {
        "name": "Hollard Life Assurance",
        "slug": "hollard-life",
        "license_number": "NIC/LF/005",
        "contact_email": "info@hollard.com.gh",
        "claims_hotline": "+233 80 044 4999",
        "is_verified": True
    },
    {
        "name": "Prudential Life Insurance Ghana",
        "slug": "prudential-life",
        "license_number": "NIC/LF/006",
        "contact_email": "customercare@prudentiallife.com.gh",
        "claims_hotline": "+233 30 220 8888",
        "is_verified": True
    },
    {
        "name": "Sanlam Life Insurance Ghana",
        "slug": "sanlam-life",
        "license_number": "NIC/LF/007",
        "contact_email": "clientcare@sanlam.com.gh",
        "claims_hotline": "+233 30 276 9623",
        "is_verified": True
    },
    {
        "name": "Old Mutual Life Assurance Ghana",
        "slug": "old-mutual-life",
        "license_number": "NIC/LF/008",
        "contact_email": "contactus@oldmutual.com.gh",
        "claims_hotline": "+233 30 700 0600",
        "is_verified": True
    },
    {
        "name": "Metropolitan Life Insurance Ghana",
        "slug": "metropolitan-life",
        "license_number": "NIC/LF/009",
        "contact_email": "info@metropolitan.com.gh",
        "claims_hotline": "+233 30 263 3999",
        "is_verified": True
    },
    {
        "name": "miLife Insurance",
        "slug": "milife-insurance",
        "license_number": "NIC/LF/010",
        "contact_email": "info@milifeghana.com",
        "claims_hotline": "+233 30 221 3400",
        "is_verified": True
    },
    {
        "name": "Vanguard Life Assurance",
        "slug": "vanguard-life",
        "license_number": "NIC/LF/011",
        "contact_email": "info@vanguardlife.com",
        "claims_hotline": "+233 30 223 5212",
        "is_verified": True
    },
    {
        "name": "Quality Life Assurance Company (QLAC)",
        "slug": "qlac-insurance",
        "license_number": "NIC/LF/012",
        "contact_email": "info@qlaclife.com",
        "claims_hotline": "+233 30 277 5612",
        "is_verified": True
    },
    {
        "name": "First National Life Insurance",
        "slug": "first-national-life",
        "license_number": "NIC/LF/013",
        "contact_email": "info@firstnationallife.com",
        "claims_hotline": "+233 30 225 8920",
        "is_verified": True
    },
    {
        "name": "Donewell Life Company",
        "slug": "donewell-life",
        "license_number": "NIC/LF/014",
        "contact_email": "info@donewelllife.com.gh",
        "claims_hotline": "+233 30 277 1774",
        "is_verified": True
    },

    # --- General / Non-Life Underwriters ---
    {
        "name": "SIC Insurance PLC",
        "slug": "sic-insurance",
        "license_number": "NIC/NL/001",
        "contact_email": "sicinfo@sic-gh.com",
        "claims_hotline": "+233 30 228 0600",
        "is_verified": True
    },
    {
        "name": "Enterprise Insurance",
        "slug": "enterprise-insurance",
        "license_number": "NIC/NL/002",
        "contact_email": "info.insurance@enterprisegroup.com.gh",
        "claims_hotline": "+233 30 263 4700",
        "is_verified": True
    },
    {
        "name": "Star Assurance Company",
        "slug": "star-assurance",
        "license_number": "NIC/NL/003",
        "contact_email": "starassurance@starassurance.com",
        "claims_hotline": "+233 30 224 0632",
        "is_verified": True
    },
    {
        "name": "GLICO General Insurance",
        "slug": "glico-general",
        "license_number": "NIC/NL/004",
        "contact_email": "info@glicogroup.com",
        "claims_hotline": "+233 30 221 8555",
        "is_verified": True
    },
    {
        "name": "Vanguard Assurance",
        "slug": "vanguard-assurance",
        "license_number": "NIC/NL/005",
        "contact_email": "info@vanguardassurance.com",
        "claims_hotline": "+233 30 221 3444",
        "is_verified": True
    },
    {
        "name": "Hollard Insurance Ghana",
        "slug": "hollard-general",
        "license_number": "NIC/NL/006",
        "contact_email": "info@hollard.com.gh",
        "claims_hotline": "+233 30 222 0085",
        "is_verified": True
    },
    {
        "name": "Activa International Insurance",
        "slug": "activa-ghana",
        "license_number": "NIC/NL/007",
        "contact_email": "info@activa-ghana.com",
        "claims_hotline": "+233 30 268 7338",
        "is_verified": True
    },
    {
        "name": "Quality Insurance Company (QIC)",
        "slug": "quality-insurance",
        "license_number": "NIC/NL/008",
        "contact_email": "info@qicghana.com",
        "claims_hotline": "+233 30 225 8295",
        "is_verified": True
    },
    {
        "name": "Priority Insurance",
        "slug": "priority-insurance",
        "license_number": "NIC/NL/009",
        "contact_email": "info@priorityinsurancegh.com",
        "claims_hotline": "+233 30 224 8833",
        "is_verified": True
    },
    {
        "name": "Serene Insurance",
        "slug": "serene-insurance",
        "license_number": "NIC/NL/010",
        "contact_email": "info@sereneinsurance.com.gh",
        "claims_hotline": "+233 30 281 9283",
        "is_verified": True
    },
    {
        "name": "Sunu Assurances Ghana",
        "slug": "sunu-assurances",
        "license_number": "NIC/NL/011",
        "contact_email": "ghana@sunu-group.com",
        "claims_hotline": "+233 30 222 1903",
        "is_verified": True
    },
    {
        "name": "Prime Insurance Company",
        "slug": "prime-insurance",
        "license_number": "NIC/NL/012",
        "contact_email": "info@primeinsuranceghana.com",
        "claims_hotline": "+233 30 223 9308",
        "is_verified": True
    }
]

print("Populating 26 verified Ghanaian underwriters...")
for item in comprehensive_insurers:
    comp = InsuranceCompany.objects.filter(
        Q(slug=item["slug"]) |
        Q(name=item["name"]) |
        Q(name=f"__TMP_{item['name']}")
    ).first()

    if comp:
        for k, v in item.items():
            setattr(comp, k, v)
        comp.save()
    else:
        InsuranceCompany.objects.create(**item)

# Purge any leftover temporary records that have no issued policies
leftovers = InsuranceCompany.objects.filter(license_number__startswith='TMP_LIC_')
for old in leftovers:
    if not old.issued_policies.exists():
        old.delete()
    else:
        old.license_number = f"NIC/ARCHIVED/{old.id}"
        old.name = old.name.replace(f"__TMP_{old.id}_", "")[:250]
        old.save(update_fields=['license_number', 'name'])

total_count = InsuranceCompany.objects.filter(is_verified=True).count()
print(f"Catalog successfully seeded: {total_count} verified underwriting institutions active in database.")