from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import (
    AssetRecord,
    ClaimSecurityAuditLog,
    ClaimantAccessGrant,
    CustomUser,
    EmergencyContact,
    EstateDocument,
    InsuranceCompany,
    PolicyClaim,
    PolicyRecord,
)

# Custom Django Admin Header & Titles
admin.site.site_header = "LegacyTrace Vault Administration"
admin.site.site_title = "LegacyTrace Portal"
admin.site.index_title = "National Estate & Policy Management"


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
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
    readonly_fields = ("access_token", "payment_reference", "unlocked_at")


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
        return f"{obj.policy.policy_number} ({obj.policyholder.get_full_name() or obj.policyholder.username})"

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
        return False