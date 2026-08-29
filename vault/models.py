import re
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db.models import Sum


# 1. Custom User Model with Profile Fields & Vault Discovery Helpers
class CustomUser(AbstractUser):
    USER_TYPE_CHOICES = (
        ('POLICYHOLDER', 'Policyholder'),
        ('STAFF', 'Staff Member'),
        ('INSURER_ADMIN', 'Insurer Administrator'),
    )

    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, default='POLICYHOLDER')
    phone_number = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    ghana_card_number = models.CharField(max_length=30, unique=True, blank=True, null=True, db_index=True)
    permanent_address = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['ghana_card_number', 'phone_number']),
            models.Index(fields=['first_name', 'last_name']),
        ]

    def save(self, *args, **kwargs):
        # Auto-normalize Ghana Card format to uppercase before saving
        if self.ghana_card_number:
            self.ghana_card_number = self.ghana_card_number.strip().upper()
        super().save(*args, **kwargs)

    @property
    def masked_ghana_card(self):
        """Returns masked card for public search privacy: GHA-XXXXX688-8"""
        if not self.ghana_card_number:
            return "Not Registered"
        card = self.ghana_card_number
        if len(card) >= 10:
            return f"{card[:6]}*"
        return card

    @property
    def clean_card_digits(self):
        """Returns pure digits from the Ghana Card ID for matching algorithms"""
        if not self.ghana_card_number:
            return ""
        return re.sub(r'\D', '', self.ghana_card_number)

    @property
    def total_policies_count(self):
        return self.policies.filter(is_active=True).count()

    @property
    def total_assets_count(self):
        return self.assets.count()

    @property
    def total_documents_count(self):
        return self.estate_documents.count()

    @property
    def primary_emergency_contact(self):
        return self.emergency_contacts.filter(is_primary=True).first() or self.emergency_contacts.first()

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_user_type_display()})"


# 2. Insurance Company / Multi-Insurer Entity
class InsuranceCompany(models.Model):
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(unique=True)
    license_number = models.CharField(max_length=100, unique=True)
    contact_email = models.EmailField()
    claims_hotline = models.CharField(max_length=50)
    logo = models.ImageField(upload_to='insurer_logos/', blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Insurance Companies"
        ordering = ['name']

    def __str__(self):
        return self.name


# 3. Emergency Contact / Next of Kin
class EmergencyContact(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="emergency_contacts"
    )
    full_name = models.CharField(max_length=255)
    relationship = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField(blank=True, null=True)
    is_primary = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_primary', '-created_at']

    def __str__(self):
        return f"{self.full_name} ({self.relationship}) - for {self.user.username}"


# 4. Relational Policy Record (Lock Enforcement, Financials & Telemetry)
class PolicyRecord(models.Model):
    POLICY_TYPES = (
        ('LIFE', 'Life Insurance'),
        ('HEALTH', 'Health Insurance'),
        ('MOTOR', 'Vehicle Insurance'),
        ('PROPERTY', 'Property / Home Insurance'),
        ('GROUP', 'Group / Corporate Policy'),
    )

    POLICY_STATUS_CHOICES = (
        ('ACTIVE', 'Active & Current'),
        ('GRACE_PERIOD', 'In Grace Period'),
        ('CLAIM_IN_PROGRESS', 'Claim In Progress'),
        ('SETTLED', 'Fully Settled / Claim Paid'),
        ('LAPSED', 'Lapsed / Inactive'),
    )

    PAYMENT_FREQUENCY_CHOICES = (
        ('MONTHLY', 'Monthly Contribution'),
        ('QUARTERLY', 'Quarterly Contribution'),
        ('ANNUALLY', 'Annual Contribution'),
        ('ONE_TIME', 'Single Lump Sum'),
    )

    policyholder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="policies"
    )
    insurer = models.ForeignKey(
        InsuranceCompany,
        on_delete=models.PROTECT,
        related_name="issued_policies"
    )
    policy_number = models.CharField(max_length=100, unique=True, db_index=True)
    policy_type = models.CharField(max_length=20, choices=POLICY_TYPES)
    policy_status = models.CharField(max_length=30, choices=POLICY_STATUS_CHOICES, default='ACTIVE')
    
    # Financial Telemetry & Contributions
    sum_assured = models.DecimalField(
        max_digits=14, 
        decimal_places=2, 
        default=50000.00,
        help_text="Guaranteed statutory payout benefit (GHS)"
    )
    total_premiums_paid = models.DecimalField(
        max_digits=14, 
        decimal_places=2, 
        default=6400.00,
        help_text="Cumulative contributions paid by policyholder to date (GHS)"
    )
    monthly_premium = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=250.00,
        help_text="Regular recurring premium obligation (GHS)"
    )
    payment_frequency = models.CharField(
        max_length=30, 
        choices=PAYMENT_FREQUENCY_CHOICES, 
        default='MONTHLY'
    )
    
    policy_start_date = models.DateField(blank=True, null=True)
    maturity_date = models.DateField(blank=True, null=True)
    
    group_admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_group_policies"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def is_claim_locked(self):
        """
        True if this policy has already been unlocked/paid for by a relative or is actively
        under settlement, locking out subsequent paid unlocks by third parties.
        """
        return (
            self.policy_status in ['CLAIM_IN_PROGRESS', 'SETTLED']
            or self.unlock_grants.filter(is_active=True).exists()
            or self.claims.exclude(status='REJECTED').exists()
        )

    @property
    def active_claimant_grant(self):
        """Returns the active verified unlock grant for this policy, if present."""
        return self.unlock_grants.filter(is_active=True).first()

    @property
    def total_disbursed_claims(self):
        """Calculates total amount disbursed for claims under this policy"""
        return self.claims.filter(status='DISBURSED').aggregate(
            total=Sum('amount_disbursed')
        )['total'] or 0.00

    @property
    def total_claimed_amount(self):
        """Calculates total claims filed under this policy"""
        return self.claims.aggregate(
            total=Sum('amount_claimed')
        )['total'] or 0.00

    @property
    def net_estimated_benefit(self):
        """Calculates remaining statutory payout after existing disbursements"""
        return max(float(self.sum_assured) - float(self.total_disbursed_claims), 0.00)

    def __str__(self):
        return f"{self.policy_number} - {self.insurer.name} ({self.policyholder.username})"


# 5. Claims History & Statutory Disbursement Ledger
class PolicyClaim(models.Model):
    CLAIM_STATUS_CHOICES = (
        ('PENDING_REVIEW', 'Under Desk Review'),
        ('DOCS_VERIFIED', 'Statutory Documents Verified'),
        ('APPROVED', 'Claim Approved for Settlement'),
        ('DISBURSED', 'Funds Disbursed to Claimant'),
        ('REJECTED', 'Claim Declined / Ineligible'),
    )

    CLAIM_TYPE_CHOICES = (
        ('DEATH_BENEFIT', 'Death Benefit / Next-of-Kin Payout'),
        ('SURVIVOR_SETTLEMENT', 'Survivor Legacy Transfer'),
        ('CRITICAL_ILLNESS', 'Critical Care Support Payout'),
        ('MATURITY_DISBURSEMENT', 'Maturity Liquidation'),
    )

    policy = models.ForeignKey(
        PolicyRecord,
        on_delete=models.CASCADE,
        related_name="claims"
    )
    claim_reference = models.CharField(max_length=100, unique=True, db_index=True)
    claim_type = models.CharField(max_length=30, choices=CLAIM_TYPE_CHOICES, default='DEATH_BENEFIT')
    claimant_filer_name = models.CharField(max_length=255, blank=True, null=True)
    amount_claimed = models.DecimalField(max_digits=14, decimal_places=2)
    amount_disbursed = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    status = models.CharField(max_length=30, choices=CLAIM_STATUS_CHOICES, default='PENDING_REVIEW')
    filing_date = models.DateField(auto_now_add=True)
    settlement_date = models.DateField(blank=True, null=True)
    insurer_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-filing_date', '-created_at']

    def __str__(self):
        return f"{self.claim_reference} ({self.get_status_display()}) - {self.policy.policy_number}"


# 6. Asset & Property Tracking
class AssetRecord(models.Model):
    ASSET_TYPES = (
        ('REAL_ESTATE', 'Real Estate / Land / Building'),
        ('VEHICLE', 'Vehicle / Automobile'),
        ('BANK_ACCOUNT', 'Bank Account / Treasury / Investment'),
        ('BUSINESS', 'Business Ownership / Equity'),
        ('OTHER', 'Other Physical Asset'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assets"
    )
    asset_type = models.CharField(max_length=30, choices=ASSET_TYPES)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    estimated_value = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)
    location_or_identifier = models.CharField(max_length=255, blank=True, null=True)
    document_proof = models.FileField(upload_to="asset_proofs/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.get_asset_type_display()}) - {self.user.username}"


# 7. Digital Wills & Estate Documents
class EstateDocument(models.Model):
    DOC_TYPES = (
        ('WILL', 'Last Will & Testament'),
        ('CODICIL', 'Will Amendment / Codicil'),
        ('TITLE_DEED', 'Title Deed / Indenture'),
        ('CERTIFICATE', 'Official Certificate'),
        ('OTHER', 'Other Legal Estate Document'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="estate_documents"
    )
    document_type = models.CharField(max_length=30, choices=DOC_TYPES)
    title = models.CharField(max_length=255)
    document_file = models.FileField(upload_to="estate_vault/")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.title} ({self.get_document_type_display()}) - {self.user.username}"


# 8. Claimant Unlock & Access Grant Audit (Captured Intake & Verified Dossier)
class ClaimantAccessGrant(models.Model):
    policyholder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="granted_claimant_accesses"
    )
    policy = models.ForeignKey(
        PolicyRecord,
        on_delete=models.CASCADE,
        related_name="unlock_grants"
    )
    claimant_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_vault_grants"
    )
    claimant_name = models.CharField(max_length=255, blank=True, null=True)
    relationship_to_deceased = models.CharField(max_length=100, blank=True, null=True)
    claimant_phone = models.CharField(max_length=20, blank=True, null=True)
    claimant_ghana_card = models.CharField(max_length=30, blank=True, null=True)
    permanent_address = models.TextField(blank=True, null=True)
    claimant_email = models.EmailField()
    payment_reference = models.CharField(max_length=150, unique=True, db_index=True)
    access_token = models.CharField(max_length=100, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    unlocked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-unlocked_at']

    def __str__(self):
        return f"Grant {self.access_token[:8]}... - {self.policyholder.username} to {self.claimant_name or self.claimant_email}"


# 9. Security & Tamper-Proof Audit Logging (Next-of-Kin Forensic Trace, Biometric Capture & IP Logging)
class ClaimSecurityAuditLog(models.Model):
    AUDIT_STATUS_CHOICES = (
        ('VERIFIED_MATCH', 'Verified Next-of-Kin Match'),
        ('UNMATCHED_FLAGGED', 'Unmatched Identity - Audit Flagged'),
        ('INVESTIGATION_PENDING', 'Under Desk Fraud Review'),
    )

    policy = models.ForeignKey(
        PolicyRecord,
        on_delete=models.CASCADE,
        related_name="security_audit_logs"
    )
    policyholder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="targeted_audit_logs"
    )
    claimant_name = models.CharField(max_length=255)
    relationship_stated = models.CharField(max_length=100)
    claimant_phone = models.CharField(max_length=20)
    claimant_ghana_card = models.CharField(max_length=30)
    claimant_email = models.EmailField()
    permanent_address = models.TextField(blank=True, null=True)

    # Forensic Network Telemetry & Device Fingerprinting
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)

    # 3-Angle Biometric Facial Snapshots & Audit Telemetry
    biometric_front_photo = models.ImageField(
        upload_to='security_audits/biometrics/front/%Y/%m/',
        blank=True,
        null=True,
        help_text="Straight-angle facial verification snapshot"
    )
    biometric_left_photo = models.ImageField(
        upload_to='security_audits/biometrics/left/%Y/%m/',
        blank=True,
        null=True,
        help_text="Left profile facial verification snapshot"
    )
    biometric_right_photo = models.ImageField(
        upload_to='security_audits/biometrics/right/%Y/%m/',
        blank=True,
        null=True,
        help_text="Right profile facial verification snapshot"
    )
    biometric_consent_granted = models.BooleanField(
        default=True,
        help_text="Records statutory consent granted for 3-angle biometric capture"
    )
    camera_permission_granted = models.BooleanField(
        default=True,
        help_text="Records whether hardware camera permission was allowed"
    )

    # Identity Validation & Fraud Review State
    is_matched = models.BooleanField(default=False)
    status = models.CharField(max_length=30, choices=AUDIT_STATUS_CHOICES, default='UNMATCHED_FLAGGED')
    disclaimer_acknowledged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Claim Security & Forensic Audit Log"
        verbose_name_plural = "Claim Security & Forensic Audit Logs"

    def __str__(self):
        match_label = "MATCHED" if self.is_matched else "UNMATCHED_FLAGGED"
        return f"[{match_label}] {self.claimant_ghana_card} ({self.claimant_name}) -> Policy {self.policy.policy_number} [{self.ip_address}]"