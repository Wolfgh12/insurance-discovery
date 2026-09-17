import secrets
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db.models import Q
from django.utils.html import format_html
from .models import (
    AssetRecord,
    CitizenMemory,
    ClaimSecurityAuditLog,
    ClaimantAccessGrant,
    ContactInquiry,
    CustomUser,
    EmergencyContact,
    EstateDocument,
    FamilyMember,
    InsuranceCompany,
    MilestonePrompt,
    PlatformConfiguration,
    PolicyClaim,
    PolicyRecord,
    SecurityQuestion,
    UserSecurityAnswer,
    UserSubscription,
)

# Custom Django Admin Header & Titles
admin.site.site_header = "LegacyTrace Vault Administration"
admin.site.site_title = "LegacyTrace Portal"
admin.site.index_title = "National Estate & Policy Management"


class UserSecurityAnswerInline(admin.TabularInline):
    model = UserSecurityAnswer
    extra = 0
    fields = ("question", "answer", "updated_at")
    readonly_fields = ("updated_at",)


class CitizenMemoryInline(admin.TabularInline):
    model = CitizenMemory
    extra = 0
    fields = ("prompt", "story_or_answer", "approximate_year_or_era", "photo", "is_flagged")
    readonly_fields = ("created_at",)


class FamilyMemberInline(admin.TabularInline):
    model = FamilyMember
    extra = 0
    fields = ("relationship", "full_name", "birth_year", "birth_place", "photo")


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    inlines = [UserSecurityAnswerInline, CitizenMemoryInline, FamilyMemberInline]
    list_display = (
        "username",
        "email",
        "admin_role_badge",
        "ghana_card_number",
        "phone_number",
        "is_active",
    )
    list_filter = (
        "is_superuser",
        "is_staff",
        "user_type",
        "is_active",
    )
    search_fields = (
        "username",
        "email",
        "first_name",
        "last_name",
        "ghana_card_number",
        "phone_number",
    )
    ordering = ("-is_superuser", "-is_staff", "username")

    fieldsets = UserAdmin.fieldsets + (
        (
            "Custom Profile Info",
            {
                "fields": (
                    "user_type",
                    "phone_number",
                    "ghana_card_number",
                    "permanent_address",
                )
            },
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Custom Profile Info",
            {
                "fields": (
                    "user_type",
                    "phone_number",
                    "ghana_card_number",
                    "permanent_address",
                )
            },
        ),
    )

    def admin_role_badge(self, obj):
        if obj.is_superuser:
            return format_html(
                '<span style="background: #FEE2E2; color: #DC2626; border: 1px solid #EF4444; padding: 2px 8px; border-radius: 6px; font-weight: 800; font-size: 0.72rem;">{}</span>',
                "👑 LEAD ADMIN"
            )
        elif obj.is_staff or obj.user_type == "STAFF":
            return format_html(
                '<span style="background: #FEF3C7; color: #D97706; border: 1px solid #F59E0B; padding: 2px 8px; border-radius: 6px; font-weight: 800; font-size: 0.72rem;">{}</span>',
                "⚙️ NORMAL ADMIN"
            )
        elif obj.user_type == "INSURER_ADMIN":
            return format_html(
                '<span style="background: #DCFCE7; color: #16A34A; border: 1px solid #10B981; padding: 2px 8px; border-radius: 6px; font-weight: 800; font-size: 0.72rem;">{}</span>',
                "🏛️ CLAIMS DESK"
            )
        return format_html(
            '<span style="background: #E0F2FE; color: #0284C7; border: 1px solid #38BDF8; padding: 2px 8px; border-radius: 6px; font-weight: 700; font-size: 0.72rem;">{}</span>',
            "👤 POLICYHOLDER"
        )

    admin_role_badge.short_description = "Role & Clearance"


@admin.register(InsuranceCompany)
class InsuranceCompanyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "license_number",
        "claims_hotline",
        "is_verified",
        "created_at",
    )
    list_filter = ("is_verified",)
    search_fields = ("name", "license_number")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(EmergencyContact)
class EmergencyContactAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "relationship",
        "phone_number",
        "user",
        "is_primary",
    )
    search_fields = ("full_name", "phone_number", "user__username")
    list_filter = ("is_primary",)


@admin.register(PolicyRecord)
class PolicyRecordAdmin(admin.ModelAdmin):
    list_display = (
        "policy_number",
        "policyholder",
        "insurer",
        "policy_type",
        "policy_status",
        "sum_assured",
        "is_active",
        "created_at",
    )
    list_filter = ("policy_type", "policy_status", "is_active", "insurer")
    search_fields = ("policy_number", "policyholder__username", "insurer__name")


@admin.register(PolicyClaim)
class PolicyClaimAdmin(admin.ModelAdmin):
    list_display = (
        "claim_reference",
        "policy",
        "claim_type",
        "claimant_filer_name",
        "amount_claimed",
        "amount_disbursed",
        "status",
        "filing_date",
    )
    list_filter = ("status", "claim_type", "filing_date")
    search_fields = (
        "claim_reference",
        "claimant_filer_name",
        "policy__policy_number",
    )


@admin.register(AssetRecord)
class AssetRecordAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "asset_type",
        "user",
        "estimated_value",
        "created_at",
    )
    list_filter = ("asset_type",)
    search_fields = ("title", "user__username", "location_or_identifier")


@admin.register(EstateDocument)
class EstateDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "document_type", "user", "uploaded_at")
    list_filter = ("document_type",)
    search_fields = ("title", "user__username")


@admin.register(ClaimantAccessGrant)
class ClaimantAccessGrantAdmin(admin.ModelAdmin):
    list_display = (
        "payment_reference",
        "claimant_name",
        "relationship_to_deceased",
        "policyholder",
        "policy",
        "is_active",
        "unlocked_at",
        "vault_direct_link",
    )
    list_filter = ("is_active", "unlocked_at")
    search_fields = (
        "payment_reference",
        "access_token",
        "claimant_name",
        "claimant_email",
        "claimant_ghana_card",
        "policyholder__username",
    )
    readonly_fields = ("access_token", "payment_reference", "unlocked_at", "vault_direct_link")

    fieldsets = (
        (
            "Claimant Identity Details",
            {
                "fields": (
                    "claimant_user",
                    "claimant_name",
                    "relationship_to_deceased",
                    "claimant_ghana_card",
                    "claimant_phone",
                    "claimant_email",
                    "permanent_address",
                ),
                "description": "Leave Claimant User blank to auto-create or auto-link an account based on Ghana Card / Email.",
            },
        ),
        (
            "Target Vault & Policy",
            {
                "fields": (
                    "policy",
                    "policyholder",
                    "is_active",
                ),
                "description": "Select the policy to unlock. Policyholder auto-populates from the policy if omitted.",
            },
        ),
        (
            "Access Telemetry & Credentials",
            {
                "fields": (
                    "payment_reference",
                    "access_token",
                    "unlocked_at",
                    "vault_direct_link",
                ),
                "description": "Generated automatically upon saving.",
            },
        ),
    )

    def vault_direct_link(self, obj):
        if obj and obj.access_token:
            return format_html(
                '<a href="/claimant/vault/{}/" target="_blank" style="background: #0284C7; color: #ffffff; padding: 3px 8px; border-radius: 6px; font-weight: 800; text-decoration: none; font-size: 0.75rem;">Open Vault ➔</a>',
                obj.access_token,
            )
        return format_html('<span style="color: #94A3B8;">{}</span>', "Unsaved")

    vault_direct_link.short_description = "Private Vault"

    def save_model(self, request, obj, form, change):
        if obj.policy and not obj.policyholder:
            obj.policyholder = obj.policy.policyholder

        if not obj.payment_reference:
            obj.payment_reference = f"ADM-LT-{secrets.token_hex(4).upper()}"

        if not obj.access_token:
            obj.access_token = secrets.token_urlsafe(24)

        if not obj.claimant_user:
            clean_card = (obj.claimant_ghana_card or "").replace("-", "").replace(" ", "").upper()
            existing_user = None

            if obj.claimant_ghana_card or obj.claimant_email:
                existing_user = CustomUser.objects.filter(
                    Q(ghana_card_number__iexact=obj.claimant_ghana_card)
                    | Q(ghana_card_number__iexact=clean_card)
                    | Q(email__iexact=obj.claimant_email)
                ).exclude(is_staff=True).exclude(is_superuser=True).first()

            if existing_user:
                obj.claimant_user = existing_user
            else:
                generated_username = f"claimant_{secrets.token_hex(3)}"
                name_parts = (obj.claimant_name or "Verified Claimant").split(" ", 1)
                first_name = name_parts[0]
                last_name = name_parts[1] if len(name_parts) > 1 else ""

                new_user = CustomUser.objects.create(
                    username=generated_username,
                    email=obj.claimant_email or f"{generated_username}@legacytrace.gov.gh",
                    first_name=first_name,
                    last_name=last_name,
                    phone_number=obj.claimant_phone or "",
                    ghana_card_number=obj.claimant_ghana_card or "",
                    permanent_address=obj.permanent_address or "",
                    user_type="POLICYHOLDER",
                )
                generated_password = f"LT-{secrets.token_hex(4).upper()}"
                new_user.set_password(generated_password)
                new_user.save()
                obj.claimant_user = new_user

        super().save_model(request, obj, form, change)

        if obj.policy and obj.policy.policy_status != "CLAIM_IN_PROGRESS":
            obj.policy.policy_status = "CLAIM_IN_PROGRESS"
            obj.policy.save(update_fields=["policy_status"])


@admin.register(ClaimSecurityAuditLog)
class ClaimSecurityAuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "biometric_thumbnail",
        "status_tag",
        "claimant_ghana_card",
        "claimant_name",
        "relationship_stated",
        "targeted_policy",
        "ip_address",
        "camera_permission_granted",
        "disclaimer_acknowledged",
    )
    list_filter = (
        "status",
        "is_matched",
        "biometric_consent_granted",
        "camera_permission_granted",
        "disclaimer_acknowledged",
        "created_at",
    )
    search_fields = (
        "claimant_name",
        "claimant_ghana_card",
        "claimant_phone",
        "claimant_email",
        "ip_address",
        "policy__policy_number",
        "policyholder__username",
        "policyholder__ghana_card_number",
    )
    readonly_fields = (
        "biometric_preview",
        "biometric_front_photo",
        "biometric_left_photo",
        "biometric_right_photo",
        "biometric_consent_granted",
        "camera_permission_granted",
        "policy",
        "policyholder",
        "claimant_name",
        "relationship_stated",
        "claimant_phone",
        "claimant_ghana_card",
        "claimant_email",
        "permanent_address",
        "ip_address",
        "user_agent",
        "is_matched",
        "status",
        "disclaimer_acknowledged",
        "created_at",
    )
    fieldsets = (
        (
            "Biometric 3-Angle Facial Verification",
            {
                "fields": (
                    "biometric_preview",
                    "biometric_front_photo",
                    "biometric_left_photo",
                    "biometric_right_photo",
                    "biometric_consent_granted",
                    "camera_permission_granted",
                )
            },
        ),
        (
            "Claimant Intake Submission",
            {
                "fields": (
                    "claimant_name",
                    "relationship_stated",
                    "claimant_phone",
                    "claimant_ghana_card",
                    "claimant_email",
                    "permanent_address",
                )
            },
        ),
        (
            "Targeted Vault Record",
            {
                "fields": (
                    "policy",
                    "policyholder",
                )
            },
        ),
        (
            "Forensic Network Telemetry",
            {
                "fields": (
                    "ip_address",
                    "user_agent",
                    "created_at",
                )
            },
        ),
        (
            "Identity Validation & Fraud Review",
            {
                "fields": (
                    "is_matched",
                    "status",
                    "disclaimer_acknowledged",
                )
            },
        ),
    )

    def targeted_policy(self, obj):
        policy_num = obj.policy.policy_number if obj.policy else "Archived / No Policy"
        holder_name = (
            (obj.policyholder.get_full_name() or obj.policyholder.username)
            if obj.policyholder
            else "Unknown Citizen"
        )
        return f"{policy_num} ({holder_name})"

    targeted_policy.short_description = "Target Policyholder"

    def status_tag(self, obj):
        if obj.is_matched:
            return format_html(
                '<span style="background: #DCFCE7; color: #15803D; padding: 3px 8px; border-radius: 6px; font-weight: bold; font-size: 0.75rem;">{}</span>',
                "✓ VERIFIED MATCH",
            )
        return format_html(
            '<span style="background: #FEE2E2; color: #B91C1C; padding: 3px 8px; border-radius: 6px; font-weight: bold; font-size: 0.75rem;">{}</span>',
            "⚠️ UNMATCHED / FLAGGED",
        )

    status_tag.short_description = "Validation Status"

    def biometric_thumbnail(self, obj):
        if obj.biometric_front_photo:
            return format_html(
                '<img src="{}" style="width: 42px; height: 42px; object-fit: cover; border-radius: 6px; border: 1.5px solid #0284C7;" alt="Front Profile" />',
                obj.biometric_front_photo.url,
            )
        if not obj.camera_permission_granted:
            return format_html(
                '<span style="color: #EF4444; font-size: 0.72rem; font-weight: 800;">{}</span>',
                "🚫 BLOCKED",
            )
        return format_html(
            '<span style="color: #94A3B8; font-size: 0.72rem;">{}</span>',
            "No Snapshot",
        )

    biometric_thumbnail.short_description = "Front Snapshot"

    def biometric_preview(self, obj):
        photos = []
        if obj.biometric_front_photo:
            photos.append(f'<div style="text-align:center;"><img src="{obj.biometric_front_photo.url}" style="width:140px; height:140px; object-fit:cover; border-radius:8px; border:2px solid #06B6D4;"/><div style="font-size:0.75rem; color:#0284C7; font-weight:bold; margin-top:4px;">1. Straight Profile</div></div>')
        if obj.biometric_left_photo:
            photos.append(f'<div style="text-align:center;"><img src="{obj.biometric_left_photo.url}" style="width:140px; height:140px; object-fit:cover; border-radius:8px; border:2px solid #06B6D4;"/><div style="font-size:0.75rem; color:#0284C7; font-weight:bold; margin-top:4px;">2. Left Profile</div></div>')
        if obj.biometric_right_photo:
            photos.append(f'<div style="text-align:center;"><img src="{obj.biometric_right_photo.url}" style="width:140px; height:140px; object-fit:cover; border-radius:8px; border:2px solid #06B6D4;"/><div style="font-size:0.75rem; color:#0284C7; font-weight:bold; margin-top:4px;">3. Right Profile</div></div>')

        if photos:
            return format_html(
                '<div style="display:flex; gap:16px; margin:8px 0 14px; flex-wrap:wrap;">{}</div>',
                format_html("".join(photos))
            )
        return format_html(
            '<span style="color: #64748B; font-style: italic;">{}</span>',
            "No 3-angle biometric snapshots available for this audit record.",
        )

    biometric_preview.short_description = "3-Angle Biometric Capture Preview"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(PlatformConfiguration)
class PlatformConfigurationAdmin(admin.ModelAdmin):
    list_display = (
        "config_summary",
        "required_questions_display",
        "unlock_fee_display",
        "annual_retainer_display",
        "active_modules_display",
        "updated_at",
    )
    fieldsets = (
        (
            "Modular Vault Global Feature Switches (Active vs. Coming Soon)",
            {
                "fields": (
                    "module_policies_enabled",
                    "module_memories_enabled",
                    "module_family_tree_enabled",
                    "module_banks_enabled",
                    "module_investments_enabled",
                    "module_assets_enabled",
                    "module_wills_enabled",
                ),
                "description": "Check a module to activate it live across the platform. Uncheck to lock it to 'Coming Soon' on the Home Page and Citizen Dashboard.",
            },
        ),
        (
            "Statutory Identity & Two-Factor Verification",
            {
                "fields": ("required_security_questions",),
                "description": "Set the exact number of security recovery keys citizens must select and answer (e.g. 3, 5, or 10).",
            },
        ),
        (
            "Statutory Fees (Unlock & Registration)",
            {
                "fields": (
                    "unlock_fee",
                    "registration_fee",
                ),
                "description": "Statutory fees collected via Paystack.",
            },
        ),
        (
            "Subscriber Retainer Pricing & Gateway",
            {
                "fields": (
                    "annual_subscription_fee",
                    "paystack_annual_plan_code",
                ),
                "description": "Annual digital estate vault retainer pricing and Paystack plan code.",
            },
        ),
    )

    def config_summary(self, obj):
        return "Global Platform Monetization Settings"
    config_summary.short_description = "Configuration Instance"

    def required_questions_display(self, obj):
        count = getattr(obj, "required_security_questions", 3)
        return format_html(
            '<span style="background: #E0F2FE; color: #0284C7; border: 1px solid #38BDF8; padding: 3px 10px; border-radius: 6px; font-weight: 800; font-size: 0.78rem;">🔐 {} Questions Required</span>',
            count,
        )
    required_questions_display.short_description = "Security Keys Count"

    def unlock_fee_display(self, obj):
        fee_str = f"{obj.unlock_fee:.2f}" if obj.unlock_fee is not None else "0.00"
        return format_html(
            '<strong style="color: #0284C7; font-size: 0.95rem;">GHS {}</strong> <span style="font-family: monospace; color: #64748B; font-size: 0.75rem;">({} pesewas)</span>',
            fee_str,
            obj.unlock_fee_pesewas,
        )
    unlock_fee_display.short_description = "Unlock Fee"

    def annual_retainer_display(self, obj):
        annual_str = f"{obj.annual_subscription_fee:.2f}" if obj.annual_subscription_fee is not None else "0.00"
        return format_html(
            '<strong style="color: #059669; font-size: 0.95rem;">GHS {}</strong> <span style="font-family: monospace; color: #64748B; font-size: 0.75rem;">[{}]</span>',
            annual_str,
            obj.paystack_annual_plan_code,
        )
    annual_retainer_display.short_description = "Annual Retainer"

    def active_modules_display(self, obj):
        active_count = sum([
            bool(obj.module_policies_enabled),
            bool(obj.module_memories_enabled),
            bool(obj.module_family_tree_enabled),
            bool(obj.module_banks_enabled),
            bool(obj.module_investments_enabled),
            bool(obj.module_assets_enabled),
            bool(obj.module_wills_enabled),
        ])
        return format_html(
            '<span style="background: #DCFCE7; color: #15803D; border: 1px solid #86EFAC; padding: 2px 8px; border-radius: 6px; font-weight: 800; font-size: 0.75rem;">{} of 7 Active</span>',
            active_count,
        )
    active_modules_display.short_description = "Live Modules"

    def has_add_permission(self, request):
        if PlatformConfiguration.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "tier_badge",
        "billing_cycle",
        "status_badge",
        "amount_paid_display",
        "current_period_end",
        "auto_renew",
    )
    list_filter = (
        "status",
        "tier",
        "billing_cycle",
        "auto_renew",
        "created_at",
    )
    search_fields = (
        "user__username",
        "user__email",
        "user__ghana_card_number",
        "paystack_customer_code",
        "paystack_subscription_code",
        "paystack_plan_code",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Subscriber & Plan Tier",
            {
                "fields": (
                    "user",
                    "tier",
                    "billing_cycle",
                    "status",
                    "auto_renew",
                )
            },
        ),
        (
            "Billing Schedule & Telemetry",
            {
                "fields": (
                    "amount_paid",
                    "current_period_start",
                    "current_period_end",
                )
            },
        ),
        (
            "Paystack Subscription Identifiers",
            {
                "fields": (
                    "paystack_customer_code",
                    "paystack_plan_code",
                    "paystack_subscription_code",
                    "paystack_authorization_code",
                    "paystack_email_token",
                )
            },
        ),
        (
            "System Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def tier_badge(self, obj):
        return format_html(
            '<span style="background: #E0F2FE; color: #0369A1; border: 1px solid #BAE6FD; padding: 2px 7px; border-radius: 6px; font-weight: 800; font-size: 0.72rem;">{}</span>',
            obj.get_tier_display()
        )
    tier_badge.short_description = "Tier"

    def status_badge(self, obj):
        if obj.is_valid:
            return format_html(
                '<span style="background: #DCFCE7; color: #15803D; border: 1px solid #BBF7D0; padding: 2px 7px; border-radius: 6px; font-weight: 800; font-size: 0.72rem;">{}</span>',
                "✓ ACTIVE"
            )
        return format_html(
            '<span style="background: #FEE2E2; color: #B91C1C; border: 1px solid #FECACA; padding: 2px 7px; border-radius: 6px; font-weight: 800; font-size: 0.72rem;">{}</span>',
            obj.get_status_display()
        )
    status_badge.short_description = "Status"

    def amount_paid_display(self, obj):
        return f"GHS {obj.amount_paid:.2f}"
    amount_paid_display.short_description = "Amount Paid"


@admin.register(ContactInquiry)
class ContactInquiryAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "status_badge",
        "full_name",
        "email",
        "phone",
        "category_badge",
    )
    list_filter = (
        "status",
        "category",
        "created_at",
    )
    search_fields = (
        "full_name",
        "email",
        "phone",
        "message",
        "admin_notes",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Claimant / Inquirer Identity",
            {
                "fields": (
                    "full_name",
                    "email",
                    "phone",
                )
            },
        ),
        (
            "Inquiry Details",
            {
                "fields": (
                    "category",
                    "message",
                )
            },
        ),
        (
            "Desk Status & Resolution Notes",
            {
                "fields": (
                    "status",
                    "admin_notes",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def status_badge(self, obj):
        if obj.status == "NEW":
            return format_html(
                '<span style="background: #FEE2E2; color: #DC2626; border: 1px solid #EF4444; padding: 2px 8px; border-radius: 6px; font-weight: 800; font-size: 0.72rem;">● NEW / UNREAD</span>'
            )
        elif obj.status == "IN_REVIEW":
            return format_html(
                '<span style="background: #FEF3C7; color: #D97706; border: 1px solid #F59E0B; padding: 2px 8px; border-radius: 6px; font-weight: 800; font-size: 0.72rem;">⏳ IN REVIEW</span>'
            )
        return format_html(
            '<span style="background: #DCFCE7; color: #15803D; border: 1px solid #10B981; padding: 2px 8px; border-radius: 6px; font-weight: 800; font-size: 0.72rem;">✓ RESOLVED</span>'
        )
    status_badge.short_description = "Desk Status"

    def category_badge(self, obj):
        return format_html(
            '<span style="background: #E0F2FE; color: #0369A1; border: 1px solid #BAE6FD; padding: 2px 7px; border-radius: 6px; font-weight: 700; font-size: 0.72rem;">{}</span>',
            obj.get_category_display()
        )
    category_badge.short_description = "Category"


@admin.register(SecurityQuestion)
class SecurityQuestionAdmin(admin.ModelAdmin):
    list_display = (
        "display_order",
        "question_text",
        "is_active",
        "total_answered_users",
        "created_at",
    )
    list_display_links = ("question_text",)
    list_editable = ("display_order", "is_active")
    list_filter = ("is_active", "created_at")
    search_fields = ("question_text",)
    ordering = ("display_order", "id")

    def total_answered_users(self, obj):
        count = obj.answered_by_users.count()
        return format_html(
            '<span style="background: #E0F2FE; color: #0369A1; padding: 2px 8px; border-radius: 6px; font-weight: 700; font-size: 0.75rem;">{} citizens</span>',
            count,
        )
    total_answered_users.short_description = "Citizens Using"

    def changelist_view(self, request, extra_context=None):
        if not SecurityQuestion.objects.exists():
            SecurityQuestion.seed_default_questions()
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(UserSecurityAnswer)
class UserSecurityAnswerAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "question",
        "answer",
        "updated_at",
    )
    search_fields = (
        "user__username",
        "user__email",
        "user__ghana_card_number",
        "question__question_text",
        "answer",
    )
    list_filter = ("question", "created_at")
    raw_id_fields = ("user",)


@admin.register(MilestonePrompt)
class MilestonePromptAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "status_badge",
        "suggested_by",
        "is_active",
        "display_order",
        "created_at",
    )
    list_display_links = ("title",)
    list_editable = ("is_active", "display_order")
    list_filter = ("status", "category", "is_active", "created_at")
    search_fields = ("title", "suggested_by__username")
    actions = ["approve_prompts", "reject_prompts"]

    def status_badge(self, obj):
        if obj.status == "APPROVED":
            return format_html(
                '<span style="background: #DCFCE7; color: #16A34A; border: 1px solid #10B981; padding: 2px 8px; border-radius: 6px; font-weight: 800; font-size: 0.72rem;">{}</span>',
                "✓ APPROVED"
            )
        elif obj.status == "PENDING_REVIEW":
            return format_html(
                '<span style="background: #FEF3C7; color: #D97706; border: 1px solid #F59E0B; padding: 2px 8px; border-radius: 6px; font-weight: 800; font-size: 0.72rem;">{}</span>',
                "⏳ PENDING REVIEW"
            )
        return format_html(
            '<span style="background: #FEE2E2; color: #DC2626; border: 1px solid #EF4444; padding: 2px 8px; border-radius: 6px; font-weight: 800; font-size: 0.72rem;">{}</span>',
            "✕ REJECTED"
        )
    status_badge.short_description = "Status"

    @admin.action(description="Approve selected milestone prompts for citizen dashboards")
    def approve_prompts(self, request, queryset):
        rows = queryset.update(status="APPROVED", is_active=True)
        self.message_user(request, f"{rows} milestone prompt(s) approved and pushed to citizen dashboards.")

    @admin.action(description="Reject selected milestone prompts")
    def reject_prompts(self, request, queryset):
        rows = queryset.update(status="REJECTED")
        self.message_user(request, f"{rows} milestone prompt(s) marked as rejected.")


@admin.register(CitizenMemory)
class CitizenMemoryAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "prompt",
        "photo_thumbnail",
        "approximate_year_or_era",
        "is_flagged",
        "created_at",
    )
    list_filter = ("is_flagged", "prompt__category", "created_at")
    search_fields = (
        "user__username",
        "user__email",
        "user__ghana_card_number",
        "prompt__title",
        "story_or_answer",
    )
    raw_id_fields = ("user", "prompt")
    actions = ["flag_prohibited_memories", "unflag_memories", "ban_violators"]

    def photo_thumbnail(self, obj):
        if obj.photo:
            return format_html(
                '<a href="{}" target="_blank"><img src="{}" style="width: 45px; height: 45px; object-fit: cover; border-radius: 8px; border: 1.5px solid #06B6D4;" /></a>',
                obj.photo.url,
                obj.photo.url,
            )
        return format_html('<span style="color: #94A3B8; font-size: 0.72rem;">{}</span>', "Text Only")
    photo_thumbnail.short_description = "Keepsake Photo"

    @admin.action(description="Flag selected memories for content review")
    def flag_prohibited_memories(self, request, queryset):
        rows = queryset.update(is_flagged=True)
        self.message_user(request, f"{rows} keepsake record(s) flagged for review.")

    @admin.action(description="Clear flag from selected memories")
    def unflag_memories(self, request, queryset):
        rows = queryset.update(is_flagged=False)
        self.message_user(request, f"{rows} keepsake record(s) unflagged.")

    @admin.action(description="Revoke & Ban Policyholders of selected memories (Violations)")
    def ban_violators(self, request, queryset):
        user_ids = queryset.values_list("user_id", flat=True).distinct()
        banned = CustomUser.objects.filter(id__in=user_ids).update(is_active=False)
        self.message_user(request, f"{banned} user account(s) permanently suspended for prohibited content.")


@admin.register(FamilyMember)
class FamilyMemberAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "relationship",
        "user",
        "birth_year",
        "birth_place",
        "photo_thumbnail",
        "created_at",
    )
    list_filter = ("relationship", "created_at")
    search_fields = (
        "full_name",
        "maiden_name",
        "birth_place",
        "user__username",
        "user__ghana_card_number",
    )
    raw_id_fields = ("user", "linked_emergency_contact")

    def photo_thumbnail(self, obj):
        if obj.photo:
            return format_html(
                '<a href="{}" target="_blank"><img src="{}" style="width: 40px; height: 40px; object-fit: cover; border-radius: 50%; border: 1.5px solid #0284C7;" /></a>',
                obj.photo.url,
                obj.photo.url,
            )
        return format_html('<span style="color: #94A3B8; font-size: 0.72rem;">{}</span>', "No Portrait")
    photo_thumbnail.short_description = "Portrait"