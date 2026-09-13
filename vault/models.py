import re
import secrets
from datetime import timedelta
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db.models import Sum
from django.utils import timezone


# 1. Custom User Model with Profile Fields & Vault Discovery Helpers
class CustomUser(AbstractUser):
    USER_TYPE_CHOICES = (
        ('POLICYHOLDER', 'Policyholder'),
        ('STAFF', 'Staff Member'),
        ('INSURER_ADMIN', 'Insurer Administrator'),
    )

    email = models.EmailField(blank=True, null=True, unique=True)
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, default='POLICYHOLDER')
    phone_number = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    ghana_card_number = models.CharField(max_length=30, unique=True, blank=True, null=True, db_index=True)
    permanent_address = models.TextField(blank=True, null=True)

    # Phone-First OTP Verification for Non-Email / Elderly Users
    phone_otp = models.CharField(max_length=6, blank=True, null=True)
    otp_created_at = models.DateTimeField(blank=True, null=True)

    # Statutory Registration Fee Tracking (One-Time GHS 10.00)
    has_paid_registration_fee = models.BooleanField(
        default=False,
        help_text="Designates whether the citizen has paid the one-time statutory registration fee."
    )
    registration_payment_reference = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Paystack transaction reference for the one-time registration fee."
    )

    # 3-Tier Security Question Recovery Keys
    security_birth_city = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Where were you born?"
    )
    security_mother_maiden_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="What is your mother's maiden name?"
    )
    security_high_school_crush = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Who was your first high school crush?"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['ghana_card_number', 'phone_number']),
            models.Index(fields=['first_name', 'last_name']),
        ]

    def generate_phone_otp(self):
        """Generates a cryptographically secure 6-digit numeric OTP and stamps creation time."""
        code = f"{secrets.randbelow(900000) + 100000}"
        self.phone_otp = code
        self.otp_created_at = timezone.now()
        self.save(update_fields=['phone_otp', 'otp_created_at'])
        return code

    def verify_phone_otp(self, candidate_code, max_valid_minutes=10):
        """Validates the candidate OTP against the stored code and expiration window."""
        if not self.phone_otp or not self.otp_created_at:
            return False
        if timezone.now() > self.otp_created_at + timedelta(minutes=max_valid_minutes):
            return False
        if str(candidate_code).strip() == self.phone_otp.strip():
            self.phone_otp = None
            self.otp_created_at = None
            self.is_active = True
            self.save(update_fields=['phone_otp', 'otp_created_at', 'is_active'])
            return True
        return False

    def save(self, *args, **kwargs):
        # Auto-normalize Ghana Card format to uppercase before saving
        if self.ghana_card_number:
            self.ghana_card_number = self.ghana_card_number.strip().upper()
        # Ensure blank emails are persisted as None to satisfy unique=True
        if not self.email:
            self.email = None
        super().save(*args, **kwargs)

    @property
    def has_security_questions_configured(self):
        """Returns True if the user has answered the required number of security questions."""
        config = PlatformConfiguration.get_solo()
        required_count = config.required_security_questions if config else 3
        if self.security_answers.count() >= required_count:
            return True
        return bool(
            self.security_birth_city
            and self.security_mother_maiden_name
            and self.security_high_school_crush
        )

    def verify_security_answer(self, question_identifier, raw_answer):
        """Case-insensitive verification supporting dynamic questions and legacy fallback."""
        if not raw_answer:
            return False
        cleaned = raw_answer.strip().lower()

        # 1. Match against dynamic UserSecurityAnswer records (by ID or prompt string)
        try:
            q_id = int(question_identifier)
            ans_record = self.security_answers.filter(question_id=q_id).first()
            if ans_record:
                return cleaned == ans_record.answer.strip().lower()
        except (ValueError, TypeError):
            pass

        ans_record = self.security_answers.filter(
            question__question_text__iexact=str(question_identifier).strip()
        ).first()
        if ans_record:
            return cleaned == ans_record.answer.strip().lower()

        # 2. Legacy fallback
        mapping = { 
            'birth_city': self.security_birth_city,
            'mother_maiden_name': self.security_mother_maiden_name,
            'high_school_crush': self.security_high_school_crush,
        }
        stored = mapping.get(question_identifier)
        if not stored:
            return False
        return cleaned == stored.strip().lower()

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
    def total_bank_accounts_count(self):
        return self.bank_accounts.filter(is_active=True).count()

    @property
    def total_investments_count(self):
        return self.investments.filter(is_active=True).count()

    @property
    def total_memories_count(self):
        return self.memories.count()

    @property
    def total_family_members_count(self):
        return self.family_tree_members.count()

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
        null=True,
        blank=True,
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
    claimant_email = models.EmailField(blank=True, null=True)
    payment_reference = models.CharField(max_length=150, unique=True, blank=True, db_index=True)
    access_token = models.CharField(max_length=100, unique=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True)
    unlocked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-unlocked_at']

    def save(self, *args, **kwargs):
        # Auto-sync policyholder from policy if not explicitly selected
        if self.policy and not self.policyholder_id:
            self.policyholder = self.policy.policyholder

        # Auto-generate administrative payment reference if missing
        if not self.payment_reference:
            self.payment_reference = f"ADM-LT-{secrets.token_hex(4).upper()}"

        # Auto-generate secure 24-byte access token if missing
        if not self.access_token:
            self.access_token = secrets.token_urlsafe(24)

        super().save(*args, **kwargs)

    def __str__(self):
        holder_name = self.policyholder.username if self.policyholder else "Unassigned"
        return f"Grant {self.access_token[:8]}... - {holder_name} to {self.claimant_name or self.claimant_email or 'Claimant'}"


# 9. Security & Tamper-Proof Audit Logging (Next-of-Kin Forensic Trace, Biometric Capture & IP Logging)
class ClaimSecurityAuditLog(models.Model):
    AUDIT_STATUS_CHOICES = (
        ('VERIFIED_MATCH', 'Verified Next-of-Kin Match'),
        ('UNMATCHED_FLAGGED', 'Unmatched Identity - Audit Flagged'),
        ('INVESTIGATION_PENDING', 'Under Desk Fraud Review'),
    )

    policy = models.ForeignKey(
        PolicyRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="security_audit_logs"
    )
    policyholder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
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
        policy_num = self.policy.policy_number if self.policy else "Archived/Deleted Policy"
        return f"[{match_label}] {self.claimant_ghana_card} ({self.claimant_name}) -> Policy {policy_num} [{self.ip_address}]"


# 10. Commercial Bank Accounts & Cash Vault Depository
class BankAccount(models.Model):
    ACCOUNT_TYPE_CHOICES = (
        ('SAVINGS', 'Savings Account'),
        ('CURRENT', 'Current / Checking Account'),
        ('FIXED_DEPOSIT', 'Fixed Deposit Account'),
        ('FOREIGN_CURRENCY', 'Foreign Currency Account (FCA/FEA)'),
        ('TREASURY_CASH', 'Call / Treasury Account'),
        ('OTHER', 'Other Bank Account'),
    )

    CURRENCY_CHOICES = (
        ('GHS', 'Ghanaian Cedi (GHS)'),
        ('USD', 'US Dollar (USD)'),
        ('GBP', 'British Pound (GBP)'),
        ('EUR', 'Euro (EUR)'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bank_accounts"
    )
    bank_name = models.CharField(
        max_length=150,
        help_text="e.g. GCB Bank, Ecobank Ghana, Stanbic Bank, Absa, Fidelity Bank"
    )
    branch_name = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="e.g. High Street, Ring Road Central, Spintex"
    )
    account_number = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Bank account number or IBAN"
    )
    account_type = models.CharField(
        max_length=30,
        choices=ACCOUNT_TYPE_CHOICES,
        default='SAVINGS'
    )
    currency = models.CharField(
        max_length=10,
        choices=CURRENCY_CHOICES,
        default='GHS'
    )
    estimated_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Optional rough balance or deposit balance for executor tracking"
    )
    document_proof = models.FileField(
        upload_to="bank_records/",
        blank=True,
        null=True,
        help_text="Account statement, deposit certificate, or passbook copy"
    )
    instructions = models.TextField(
        blank=True,
        null=True,
        help_text="Claim guidance or special instructions for family and executors"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Bank Account"
        verbose_name_plural = "Bank Accounts"

    @property
    def masked_account_number(self):
        """Returns masked format for security: *******1234"""
        if len(self.account_number) > 4:
            return f"{'*' * (len(self.account_number) - 4)}{self.account_number[-4:]}"
        return self.account_number

    def __str__(self):
        return f"{self.bank_name} ({self.masked_account_number}) - {self.user.username}"


# 11. Investments, Securities & Asset Portfolio Ledger
class InvestmentHolding(models.Model):
    INVESTMENT_TYPE_CHOICES = (
        ('TREASURY_BILL', 'Government of Ghana Treasury Bill (91/182/364-Day)'),
        ('MUTUAL_FUND', 'Mutual Fund / Collective Investment Scheme'),
        ('EQUITY_SHARES', 'Listed Equities / GSE Shares'),
        ('TIER3_PENSION', 'Tier-3 Provident / Voluntary Private Pension'),
        ('GOVT_BOND', 'Government / Corporate Bond'),
        ('OTHER', 'Other Investment Asset'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="investments"
    )
    institution_or_broker = models.CharField(
        max_length=150,
        help_text="Fund manager, issuing bank, or brokerage firm (e.g. Databank, EDC, CalBank Brokerage)"
    )
    investment_type = models.CharField(
        max_length=30,
        choices=INVESTMENT_TYPE_CHOICES,
        default='TREASURY_BILL'
    )
    portfolio_reference = models.CharField(
        max_length=100,
        db_index=True,
        help_text="CSD account number, investor ID, or mutual fund portfolio number"
    )
    title = models.CharField(
        max_length=255,
        help_text="e.g. Databank MFund, 182-Day GoG T-Bill, MTN Ghana Shares"
    )
    face_or_invested_value = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Initial investment amount or principal face value (GHS)"
    )
    maturity_date = models.DateField(
        blank=True,
        null=True,
        help_text="Maturity date if applicable (e.g. for T-Bills or fixed bonds)"
    )
    document_proof = models.FileField(
        upload_to="investment_proofs/",
        blank=True,
        null=True,
        help_text="CSD statement, investment contract certificate, or purchase slip"
    )
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Special instructions, rollover directives, or broker contacts"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Investment Holding"
        verbose_name_plural = "Investment Holdings"

    def __str__(self):
        return f"{self.title} - {self.institution_or_broker} ({self.user.username})"


# 12. Global Platform Configuration & Statutory Fee Settings
class PlatformConfiguration(models.Model):
    unlock_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=50.00,
        help_text="Claimant dossier unlock fee charged via Paystack (GHS)"
    )
    registration_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=10.00,
        help_text="One-time citizen vault registration fee charged via Paystack (GHS)"
    )
    annual_subscription_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=1200.00,
        help_text="Annual digital estate vault retainer fee (GHS)"
    )
    quarterly_subscription_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=450.00,
        help_text="Quarterly digital estate vault retainer fee (GHS)"
    )
    paystack_annual_plan_code = models.CharField(
        max_length=100,
        default="PLN_14xz26jx9j3gakp",
        help_text="Paystack Plan Code for Annual Retainer"
    )
    paystack_quarterly_plan_code = models.CharField(
        max_length=100,
        default="PLN_1gba1fu8sg69ik0",
        help_text="Paystack Plan Code for Quarterly Retainer"
    )
    required_security_questions = models.PositiveIntegerField(
        default=3,
        help_text="Number of security questions a citizen must select and answer during registration or setup (e.g. 3, 5, or 10)."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Platform Configuration"
        verbose_name_plural = "Platform Configuration"

    @property
    def unlock_fee_pesewas(self):
        return int(self.unlock_fee * 100)

    @property
    def registration_fee_pesewas(self):
        return int(self.registration_fee * 100)

    @property
    def annual_fee_pesewas(self):
        return int(self.annual_subscription_fee * 100)

    @property
    def quarterly_fee_pesewas(self):
        return int(self.quarterly_subscription_fee * 100)

    @classmethod
    def get_solo(cls):
        config, _ = cls.objects.get_or_create(
            id=1,
            defaults={
                'unlock_fee': 50.00,
                'registration_fee': 10.00,
                'annual_subscription_fee': 1200.00,
                'quarterly_subscription_fee': 450.00,
                'paystack_annual_plan_code': 'PLN_14xz26jx9j3gakp',
                'paystack_quarterly_plan_code': 'PLN_1gba1fu8sg69ik0',
                'required_security_questions': 3,
            }
        )
        return config

    def __str__(self):
        return f"Global Configuration (Unlock: GHS {self.unlock_fee}, Required Security Questions: {self.required_security_questions})"


# 13. Policyholder Subscription & Paystack Recurring Retainer
class UserSubscription(models.Model):
    TIER_CHOICES = (
        ('STANDARD', 'Individual Custody'),
        ('SOVEREIGN', 'Sovereign Family Vault'),
    )

    BILLING_CYCLE_CHOICES = (
        ('QUARTERLY', 'Quarterly Contribution'),
        ('ANNUALLY', 'Annual Contribution'),
    )

    STATUS_CHOICES = (
        ('ACTIVE', 'Active & Current'),
        ('PAST_DUE', 'Past Due (Grace Period)'),
        ('EXPIRED', 'Expired / Locked'),
        ('CANCELLED', 'Cancelled'),
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscription"
    )
    tier = models.CharField(max_length=20, choices=TIER_CHOICES, default='STANDARD')
    billing_cycle = models.CharField(max_length=20, choices=BILLING_CYCLE_CHOICES, default='ANNUALLY')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')

    # Paystack Subscription & Customer Identifiers
    paystack_customer_code = models.CharField(max_length=100, blank=True, null=True)
    paystack_plan_code = models.CharField(max_length=100, blank=True, null=True)
    paystack_subscription_code = models.CharField(max_length=100, blank=True, null=True)
    paystack_email_token = models.CharField(max_length=100, blank=True, null=True)
    paystack_authorization_code = models.CharField(max_length=100, blank=True, null=True)

    # Billing Telemetry & Validity Windows
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    current_period_start = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField()
    auto_renew = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "User Subscription"
        verbose_name_plural = "User Subscriptions"

    @property
    def is_valid(self):
        """Returns True if subscription status is active and not past the current end date."""
        return self.status == 'ACTIVE' and self.current_period_end >= timezone.now()

    def __str__(self):
        return f"{self.user.username} - {self.get_tier_display()} ({self.get_billing_cycle_display()}) [{self.status}]"


# 14. Inbound Contact Inquiries & Support Tickets
class ContactInquiry(models.Model):
    CATEGORY_CHOICES = (
        ('GENERAL', 'General Support'),
        ('POLICY_LINKING', 'Policy Linking & Sync'),
        ('CLAIMANT_VERIFY', 'Next-of-Kin Verification'),
        ('SUBSCRIPTION', 'Vault Protection Plans'),
        ('UNDERWRITER', 'Insurer Integration'),
    )

    STATUS_CHOICES = (
        ('NEW', 'New / Unread'),
        ('IN_REVIEW', 'In Desk Review'),
        ('RESOLVED', 'Resolved / Closed'),
    )

    full_name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True, null=True)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='GENERAL')
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NEW')
    admin_notes = models.TextField(blank=True, null=True, help_text="Internal desk notes regarding resolution")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Contact Inquiry"
        verbose_name_plural = "Contact Inquiries"

    def __str__(self):
        return f"[{self.get_status_display()}] {self.full_name} - {self.get_category_display()} ({self.created_at.strftime('%Y-%m-%d')})"


# 15. Admin-Controlled Statutory Security Questions Pool
class SecurityQuestion(models.Model):
    question_text = models.CharField(
        max_length=255,
        unique=True,
        help_text="Statutory identity verification question prompt"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Active questions appear in citizen registration and setup forms"
    )
    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Ordering rank in dropdown selectors"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'id']
        verbose_name = "Security Question"
        verbose_name_plural = "Security Questions"

    @classmethod
    def seed_default_questions(cls):
        """Seeds the standard 10 national identity recovery questions if the table is empty."""
        default_prompts = [
            "Where were you born? (City / Town)",
            "What is your mother's maiden surname?",
            "Who was your first high school crush?",
            "What was the name of your first primary / elementary school?",
            "What was the make or model of your first vehicle or bicycle?",
            "In which town or village did your parents first meet?",
            "What was the name of your favorite childhood pet?",
            "What was your childhood nickname among family?",
            "What was your favorite traditional meal growing up?",
            "What was your first official job or apprenticeship?",
        ]
        for idx, prompt in enumerate(default_prompts, start=1):
            cls.objects.get_or_create(
                question_text=prompt,
                defaults={'display_order': idx, 'is_active': True}
            )

    def __str__(self):
        status = "Active" if self.is_active else "Disabled"
        return f"{self.question_text} [{status}]"


# 16. Citizen-Bound Security Question Answers
class UserSecurityAnswer(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="security_answers"
    )
    question = models.ForeignKey(
        SecurityQuestion,
        on_delete=models.PROTECT,
        related_name="answered_by_users"
    )
    answer = models.CharField(
        max_length=255,
        help_text="Case-insensitive verification string"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['question__display_order', 'created_at']
        unique_together = ('user', 'question')
        verbose_name = "User Security Answer"
        verbose_name_plural = "User Security Answers"

    def __str__(self):
        return f"{self.user.username} -> {self.question.question_text[:35]}..."


# 17. Milestone Prompts Directory & Citizen Suggestion Pool
class MilestonePrompt(models.Model):
    CATEGORY_CHOICES = (
        ('FIRSTS', 'Firsts & Early Milestones'),
        ('FAMILY_LEGACY', 'Family Heritage & Lineage'),
        ('ACHIEVEMENTS', 'Achievements & Career'),
        ('TRIVIA', 'Personal Trivia & Favorites'),
        ('OTHER', 'Other Memories'),
    )

    STATUS_CHOICES = (
        ('APPROVED', 'Approved & Live'),
        ('PENDING_REVIEW', 'Pending Admin Review'),
        ('REJECTED', 'Rejected / Ineligible'),
    )

    title = models.CharField(
        max_length=255,
        unique=True,
        help_text="Milestone title (e.g. First Car, First Kiss, Childhood Nickname)"
    )
    category = models.CharField(
        max_length=30,
        choices=CATEGORY_CHOICES,
        default='FIRSTS'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='APPROVED',
        help_text="Only APPROVED milestones appear for citizens to select on their dashboard."
    )
    suggested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="suggested_milestones",
        help_text="Citizen who suggested this milestone (blank if created by administrator)."
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Toggle switch to hide or show without deleting."
    )
    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Ordering rank in dropdown selectors."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'title']
        verbose_name = "Milestone Prompt"
        verbose_name_plural = "Milestone Prompts"

    @classmethod
    def seed_default_prompts(cls):
        """Seeds standard milestone categories if catalog is empty."""
        defaults = [
            ("First Car / Vehicle", "FIRSTS", 1),
            ("First Job / Apprenticeship", "FIRSTS", 2),
            ("First High School Crush / Kiss", "FIRSTS", 3),
            ("First Family Home / Childhood Residence", "FAMILY_LEGACY", 4),
            ("Favorite Traditional Meal Growing Up", "TRIVIA", 5),
            ("Childhood Family Nickname", "TRIVIA", 6),
            ("Major Personal Milestone / Career Breakthrough", "ACHIEVEMENTS", 7),
            ("Favorite Family Tradition or Vacation", "FAMILY_LEGACY", 8),
        ]
        for title, cat, order in defaults:
            cls.objects.get_or_create(
                title=title,
                defaults={
                    'category': cat,
                    'display_order': order,
                    'status': 'APPROVED',
                    'is_active': True,
                }
            )

    def __str__(self):
        return f"{self.title} ({self.get_category_display()}) [{self.get_status_display()}]"


# 18. Citizen Keepsakes & Digital Time Capsule (The Memory Dump)
class CitizenMemory(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memories"
    )
    prompt = models.ForeignKey(
        MilestonePrompt,
        on_delete=models.PROTECT,
        related_name="citizen_memories"
    )
    story_or_answer = models.TextField(
        help_text="Personal story, trivia details, or milestone narrative."
    )
    photo = models.ImageField(
        upload_to='vault_memories/%Y/%m/',
        blank=True,
        null=True,
        help_text="Memorable picture attached to this milestone."
    )
    approximate_year_or_era = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="e.g. Circa 1994, Summer 2005, Class of 2010"
    )
    is_flagged = models.BooleanField(
        default=False,
        help_text="Flagged for administrative review if reported or prohibited."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Citizen Memory & Keepsake"
        verbose_name_plural = "Citizen Memories & Keepsakes"

    def __str__(self):
        return f"{self.user.username} - {self.prompt.title}"


# 19. Interactive Family Lineage & Ancestral Tree
class FamilyMember(models.Model):
    RELATIONSHIP_CHOICES = (
        ('GRANDPARENT', 'Grandparent'),
        ('FATHER', 'Father'),
        ('MOTHER', 'Mother'),
        ('SPOUSE', 'Spouse / Partner'),
        ('SIBLING', 'Sibling (Brother / Sister)'),
        ('CHILD', 'Child (Son / Daughter)'),
        ('GRANDCHILD', 'Grandchild'),
        ('OTHER', 'Other Relative'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="family_tree_members"
    )
    relationship = models.CharField(
        max_length=30,
        choices=RELATIONSHIP_CHOICES
    )
    full_name = models.CharField(
        max_length=255,
        help_text="Full legal or ancestral name"
    )
    maiden_name = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Maiden name (if applicable)"
    )
    birth_year = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="e.g. 1954, or exact birth date"
    )
    birth_place = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Town / City of birth (e.g. Kumasi, Mampong, Accra)"
    )
    photo = models.ImageField(
        upload_to='family_tree/%Y/%m/',
        blank=True,
        null=True,
        help_text="Portrait or vintage photograph"
    )
    bio_notes = models.TextField(
        blank=True,
        null=True,
        help_text="Biographical notes, ancestral clan, or memorable anecdotes"
    )
    linked_emergency_contact = models.ForeignKey(
        EmergencyContact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="family_tree_nodes",
        help_text="Link to existing statutory next-of-kin contact if applicable"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['relationship', 'full_name']
        verbose_name = "Family Tree Member"
        verbose_name_plural = "Family Tree Members"

    def __str__(self):
        return f"{self.full_name} ({self.get_relationship_display()}) - {self.user.username}'s Lineage"