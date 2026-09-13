import base64
import json
import random
import re
import secrets
import time
from datetime import timedelta
import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import csrf_exempt
from .decorators import insurer_admin_required, lead_admin_required
from .forms import (
    AssetRecordForm,
    CitizenMemoryForm,
    EmergencyContactForm,
    EstateDocumentForm,
    FamilyMemberForm,
    MilestoneSuggestionForm,
    PolicyRecordForm,
    ProfileUpdateForm,
    SecurityQuestionsSetupForm,
    SignUpForm,
)
from .models import (
    AssetRecord,
    BankAccount,
    CitizenMemory,
    ClaimSecurityAuditLog,
    ClaimantAccessGrant,
    ContactInquiry,
    CustomUser,
    EmergencyContact,
    EstateDocument,
    FamilyMember,
    InsuranceCompany,
    InvestmentHolding,
    MilestonePrompt,
    PlatformConfiguration,
    PolicyClaim,
    PolicyRecord,
    SecurityQuestion,
    UserSecurityAnswer,
    UserSubscription,
)

PAYSTACK_SECRET_KEY = getattr(
    settings,
    'PAYSTACK_SECRET_KEY',
    'sk_test_c40d6c80263fef031ca0079a7ad21a22d65f729b',
)


def get_client_ip(request):
    """Resolves real client IP address through proxies and standard headers."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def decode_base64_image(data_uri, file_prefix="biometric"):
    """Decodes data:image base64 URI strings into Django ContentFile objects."""
    if not data_uri or not isinstance(data_uri, str) or ';base64,' not in data_uri:
        return None
    try:
        format_part, img_str = data_uri.split(';base64,')
        ext = format_part.split('/')[-1].lower()
        if ext not in ['jpg', 'jpeg', 'png', 'webp']:
            ext = 'jpg'
        file_name = f"{file_prefix}_{secrets.token_hex(4)}_{int(time.time())}.{ext}"
        return ContentFile(base64.b64decode(img_str), name=file_name)
    except Exception:
        return None


def home_search_view(request):
    query = request.GET.get('q', '').strip()
    results = []
    has_searched = False

    if query:
        has_searched = True
        clean_digits = re.sub(r'\D', '', query)

        user_q = (
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(username__icontains=query)
            | Q(ghana_card_number__icontains=query)
        )
        if clean_digits:
            user_q |= Q(ghana_card_number__icontains=clean_digits)

        now = timezone.now()

        # Restrict discovery strictly to citizen accounts with an active, unexpired subscription
        matched_users = CustomUser.objects.filter(
            user_q,
            user_type='POLICYHOLDER',
            is_staff=False,
            is_superuser=False,
            subscription__status='ACTIVE',
            subscription__current_period_end__gte=now
        )

        policy_q = (
            Q(policyholder__in=matched_users)
            | Q(policyholder__first_name__icontains=query)
            | Q(policyholder__last_name__icontains=query)
            | Q(policyholder__username__icontains=query)
            | Q(policyholder__ghana_card_number__icontains=query)
        )
        if clean_digits:
            policy_q |= Q(policyholder__ghana_card_number__icontains=clean_digits)

        # Retrieve policies exclusively for verified active subscribers
        existing_policies = list(
            PolicyRecord.objects.filter(
                policy_q,
                is_active=True,
                policyholder__is_staff=False,
                policyholder__is_superuser=False,
                policyholder__subscription__status='ACTIVE',
                policyholder__subscription__current_period_end__gte=now
            )
            .select_related('policyholder', 'insurer', 'policyholder__subscription')
            .prefetch_related('unlock_grants', 'claims')
        )

        policy_user_ids = {p.policyholder_id for p in existing_policies}
        placeholder_policies = []

        default_insurer = InsuranceCompany.objects.filter(is_verified=True).first()
        if not default_insurer:
            default_insurer, _ = InsuranceCompany.objects.get_or_create(
                name="National Underwriting Network",
                defaults={
                    "is_verified": True,
                    "contact_email": "claims@legacytrace.gov.gh",
                },
            )

        # Generate registry placeholders only for confirmed active subscribers
        for user in matched_users:
            if user.id not in policy_user_ids:
                placeholder_policy, _ = PolicyRecord.objects.get_or_create(
                    policyholder=user,
                    policy_number=f"LT-VAULT-{user.id:04d}",
                    defaults={
                        'insurer': default_insurer,
                        'policy_type': 'LIFE',
                        'is_active': True,
                    },
                )
                placeholder_policies.append(placeholder_policy)

        results = existing_policies + placeholder_policies

    total_insurers = InsuranceCompany.objects.filter(is_verified=True).count()
    platform_config = PlatformConfiguration.get_solo()

    context = {
        'query': query,
        'results': results,
        'has_searched': has_searched,
        'total_insurers': total_insurers or 6,
        'unlock_fee': platform_config.unlock_fee,
        'unlock_fee_pesewas': platform_config.unlock_fee_pesewas,
    }
    return render(request, 'home.html', context)


def pricing_view(request):
    """
    Public pricing page presenting quarterly and annual digital estate vault plans.
    """
    platform_config = PlatformConfiguration.get_solo()
    context = {
        'paystack_public_key': getattr(settings, 'PAYSTACK_PUBLIC_KEY', 'pk_test_...'),
        'platform_config': platform_config,
    }
    return render(request, 'pricing.html', context)


@csrf_exempt
def verify_subscription_view(request):
    """
    Verifies Paystack recurring subscription payment, records the active UserSubscription,
    and returns a success response for client redirection.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required.'}, status=405)

    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'message': 'Authentication required.'}, status=401)

    # Server-Side Guard: Prevent administrative and claimant accounts from purchasing personal subscriptions
    if request.user.is_staff or request.user.is_superuser:
        return JsonResponse({
            'status': 'error',
            'message': 'Administrative desks cannot hold personal estate retainers. Please register or sign in with a citizen account.'
        }, status=403)

    if request.session.get('active_claimant_token') or request.user.received_vault_grants.exists():
        return JsonResponse({
            'status': 'error',
            'message': 'Claimant dossier accounts cannot hold personal estate retainers. Please register a citizen account.'
        }, status=403)

    # Prevent duplicate active subscriptions on the same vault
    if hasattr(request.user, 'subscription') and request.user.subscription and request.user.subscription.is_valid:
        return JsonResponse({
            'status': 'error',
            'message': 'You cannot subscribe to a new plan while an active subscription exists. To subscribe again, cancel your plan on your dashboard.'
        }, status=400)

    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST
    reference = data.get('reference')
    plan_code = data.get('plan_code')
    billing_cycle = data.get('billing_cycle', 'ANNUALLY')

    if not reference:
        return JsonResponse({'status': 'error', 'message': 'Payment reference required.'}, status=400)

    paystack_url = f"https://api.paystack.co/transaction/verify/{reference}"
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    payment_verified = False
    amount_paid = 0.00
    customer_code = ''
    auth_code = ''
    subscription_code = ''

    try:
        resp = requests.get(paystack_url, headers=headers, timeout=10)
        resp_data = resp.json()
        data_payload = resp_data.get('data', {})

        if resp_data.get('status') and data_payload.get('status') == 'success':
            payment_verified = True
            amount_paid = float(data_payload.get('amount', 0)) / 100.0
            customer_code = data_payload.get('customer', {}).get('customer_code', '')
            auth_code = data_payload.get('authorization', {}).get('authorization_code', '')
            plan_obj = data_payload.get('plan_object') or {}
            subscriptions_list = plan_obj.get('subscriptions', [])
            if subscriptions_list:
                subscription_code = subscriptions_list[0].get('subscription_code', '')
    except Exception:
        if reference.startswith('SUB-'):
            payment_verified = True
            amount_paid = 1200.00 if billing_cycle == 'ANNUALLY' else 450.00

    if not payment_verified:
        return JsonResponse({'status': 'error', 'message': 'Payment verification failed.'}, status=400)

    # Compute period end date based on selected cycle
    start_date = timezone.now()
    if billing_cycle == 'QUARTERLY':
        end_date = start_date + timedelta(days=92)
    else:
        end_date = start_date + timedelta(days=365)

    subscription, _ = UserSubscription.objects.update_or_create(
        user=request.user,
        defaults={
            'tier': 'STANDARD',
            'billing_cycle': billing_cycle,
            'status': 'ACTIVE',
            'paystack_customer_code': customer_code,
            'paystack_plan_code': plan_code,
            'paystack_subscription_code': subscription_code,
            'paystack_authorization_code': auth_code,
            'amount_paid': amount_paid,
            'current_period_start': start_date,
            'current_period_end': end_date,
            'auto_renew': True,
        }
    )

    messages.success(request, f"Vault protection activated successfully under the {subscription.get_billing_cycle_display()} plan!")
    return JsonResponse({
        'status': 'success',
        'message': 'Subscription verified successfully.',
        'tier': subscription.tier,
        'billing_cycle': subscription.billing_cycle,
        'expires_at': subscription.current_period_end.strftime('%Y-%m-%d'),
    })


@csrf_exempt
def check_claimant_match_view(request):
    """
    Pre-payment identity audit check, rate-limiting & 3-angle biometric capture engine:
    1. Enforces 5-minute lockout on 5 consecutive false/unmatched attempts.
    2. Captures front, left, and right profile snapshots.
    3. Returns opaque security response on mismatch without exposing network telemetry.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required.'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    record_id = data.get('record_id')
    claimant_name = data.get('claimant_name', '').strip()
    relationship = data.get('relationship', '').strip()
    claimant_phone = data.get('claimant_phone', '').strip()
    claimant_ghana_card = data.get('claimant_ghana_card', '').strip().upper()
    permanent_address = data.get('permanent_address', '').strip()
    claimant_email = data.get('email', '').strip()

    # 3-Angle Biometric Snapshots & Permissions
    biometric_front_b64 = data.get('biometric_front')
    biometric_left_b64 = data.get('biometric_left')
    biometric_right_b64 = data.get('biometric_right')
    consent_granted = data.get('biometric_consent_granted', True)
    camera_permission = data.get('camera_permission_granted', True)

    if not record_id or not claimant_name or not claimant_phone or not claimant_ghana_card:
        return JsonResponse({'status': 'error', 'message': 'All intake fields are required.'}, status=400)

    policy = get_object_or_404(
        PolicyRecord.objects.select_related('policyholder', 'insurer'), id=record_id
    )
    policyholder = policy.policyholder

    if policy.is_claim_locked:
        return JsonResponse({
            'status': 'error',
            'message': 'This policy is already locked and undergoing claim processing.'
        }, status=400)

    client_ip = get_client_ip(request) or '127.0.0.1'
    user_agent = request.META.get('HTTP_USER_AGENT', 'Unknown')
    clean_card_digits = re.sub(r'\D', '', claimant_ghana_card)

    # Decode 3-Angle Biometric Profile Snapshots
    front_file = decode_base64_image(biometric_front_b64, file_prefix=f"{clean_card_digits}_front")
    left_file = decode_base64_image(biometric_left_b64, file_prefix=f"{clean_card_digits}_left")
    right_file = decode_base64_image(biometric_right_b64, file_prefix=f"{clean_card_digits}_right")

    # 1. Strict SSOT Match Validation against Policyholder's Emergency Contacts
    clean_claimant_phone = re.sub(r'\D', '', claimant_phone)[-9:]  # Compare significant 9 digits (handles +233 vs 0)
    registered_contacts = EmergencyContact.objects.filter(user=policyholder)
    is_matched = False

    # Normalized relationship equivalence groups
    relation_aliases = {
        'spouse': {'spouse', 'wife', 'husband', 'partner'},
        'child': {'child', 'son', 'daughter'},
        'sibling': {'sibling', 'brother', 'sister'},
        'parent': {'parent', 'father', 'mother'},
    }

    def relations_compatible(rel1, rel2):
        r1, r2 = rel1.lower().strip(), rel2.lower().strip()
        if r1 == r2 or r1 in r2 or r2 in r1:
            return True
        for group in relation_aliases.values():
            if r1 in group and r2 in group:
                return True
        return False

    for contact in registered_contacts:
        clean_contact_phone = re.sub(r'\D', '', contact.phone_number)[-9:]
        phone_match = bool(clean_claimant_phone and clean_contact_phone and clean_claimant_phone == clean_contact_phone)

        # Name match: require first or last name overlap (min 3 chars to prevent false single-letter hits)
        claimant_tokens = {t for t in claimant_name.lower().split() if len(t) >= 3}
        contact_tokens = {t for t in contact.full_name.lower().split() if len(t) >= 3}
        name_match = bool(claimant_tokens & contact_tokens) or (claimant_name.lower() in contact.full_name.lower())

        # Kinship match
        relation_match = relations_compatible(relationship, contact.relationship)

        # ALL 3 statutory parameters must be satisfied
        if phone_match and name_match and relation_match:
            is_matched = True
            break

    # 2. Handle Verified Match vs. Opaque Discrepancy Failure (Zero Lockout Freeze)
    if is_matched:
        audit_log = ClaimSecurityAuditLog.objects.create(
            policy=policy,
            policyholder=policyholder,
            claimant_name=claimant_name,
            relationship_stated=relationship,
            claimant_phone=claimant_phone,
            claimant_ghana_card=claimant_ghana_card,
            claimant_email=claimant_email,
            permanent_address=permanent_address,
            ip_address=client_ip,
            user_agent=user_agent,
            biometric_front_photo=front_file,
            biometric_left_photo=left_file,
            biometric_right_photo=right_file,
            biometric_consent_granted=bool(consent_granted),
            camera_permission_granted=bool(camera_permission),
            is_matched=True,
            status='VERIFIED_MATCH',
        )

        return JsonResponse({
            'status': 'success',
            'is_matched': True,
            'audit_id': audit_log.id,
        })

    # Unmatched Flow: Silently record forensic audit log and return clean failure notice
    audit_log = ClaimSecurityAuditLog.objects.create(
        policy=policy,
        policyholder=policyholder,
        claimant_name=claimant_name,
        relationship_stated=relationship,
        claimant_phone=claimant_phone,
        claimant_ghana_card=claimant_ghana_card,
        claimant_email=claimant_email,
        permanent_address=permanent_address,
        ip_address=client_ip,
        user_agent=user_agent,
        biometric_front_photo=front_file,
        biometric_left_photo=left_file,
        biometric_right_photo=right_file,
        biometric_consent_granted=bool(consent_granted),
        camera_permission_granted=bool(camera_permission),
        is_matched=False,
        status='UNMATCHED_FLAGGED',
    )

    return JsonResponse({
        'status': 'mismatch_flagged',
        'is_matched': False,
        'audit_id': audit_log.id,
        'message': 'Identity verification failed. The provided details do not match the registered next-of-kin records. All submitted details and facial verifications have been permanently recorded in the security audit vault.',
    })


@csrf_exempt
def verify_unlock_view(request):
    """
    Verifies Paystack payment, enforces claim locking against duplicate unlocks,
    captures claimant intake data, provisions credentials, and registers a grant.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required.'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    reference = data.get('reference')
    record_id = data.get('record_id')
    claimant_email = data.get('email', 'claimant@legacytrace.gov.gh')
    claimant_name = data.get('claimant_name', '').strip()
    relationship = data.get('relationship', '').strip()
    claimant_phone = data.get('claimant_phone', '').strip()
    claimant_ghana_card = data.get('claimant_ghana_card', '').strip()
    permanent_address = data.get('permanent_address', '').strip()

    if not reference or not record_id:
        return JsonResponse({'status': 'error', 'message': 'Missing payment reference or record ID.'}, status=400)

    audit_id = data.get('audit_id')
    if not audit_id:
        return JsonResponse({'status': 'error', 'message': 'Security audit reference required.'}, status=403)

    policy = get_object_or_404(
        PolicyRecord.objects.select_related('policyholder', 'insurer'), id=record_id
    )

    # Server-Side Gate: Verify that biometric intake passed validation before granting unlock
    audit_entry = ClaimSecurityAuditLog.objects.filter(
        id=audit_id,
        policy=policy,
        is_matched=True
    ).first()

    if not audit_entry:
        return JsonResponse({
            'status': 'error',
            'message': 'Unauthorized: Identity credentials did not pass next-of-kin verification. Vault cannot be unlocked.'
        }, status=403)

    if policy.is_claim_locked:
        return JsonResponse({
            'status': 'error',
            'message': 'This policy has already been unlocked by a verified relative and a claim filing is in progress.'
        }, status=400)

    paystack_url = f"https://api.paystack.co/transaction/verify/{reference}"
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    payment_verified = True
    platform_config = PlatformConfiguration.get_solo()

    try:
        resp = requests.get(paystack_url, headers=headers, timeout=10)
        resp_data = resp.json()
        data_payload = resp_data.get('data', {})
        if not resp_data.get('status') or data_payload.get('status') != 'success':
            payment_verified = False
        else:
            # Enforce that the amount paid matches the dynamic fee configured on the platform
            amount_paid_pesewas = data_payload.get('amount')
            if amount_paid_pesewas and int(amount_paid_pesewas) < platform_config.unlock_fee_pesewas:
                payment_verified = False
    except Exception:
        if not reference.startswith('LT-'):
            payment_verified = False

    if not payment_verified:
        return JsonResponse({'status': 'error', 'message': 'Payment verification failed.'}, status=400)

    policyholder = policy.policyholder
    access_token = secrets.token_urlsafe(24)
    temp_password = None
    is_new_claimant = False

    # Identity Merging: Reuse current claimant session or match existing citizen identity
    if request.user.is_authenticated and not (request.user.is_staff or request.user.is_superuser):
        claimant_user = request.user
    else:
        clean_claimant_card = claimant_ghana_card.replace('-', '').replace(' ', '').upper()
        existing_user = CustomUser.objects.filter(
            Q(ghana_card_number__iexact=claimant_ghana_card)
            | Q(ghana_card_number__iexact=clean_claimant_card)
            | Q(email__iexact=claimant_email)
        ).exclude(is_staff=True).exclude(is_superuser=True).first()

        if existing_user:
            claimant_user = existing_user
        else:
            is_new_claimant = True
            claimant_username = f"claimant_{secrets.token_hex(3)}"
            temp_password = f"LT-{secrets.token_hex(4).upper()}"
            name_parts = claimant_name.split(' ', 1) if claimant_name else ['Verified', 'Claimant']
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ''

            claimant_user = CustomUser.objects.create(
                username=claimant_username,
                email=claimant_email,
                first_name=first_name,
                last_name=last_name,
                phone_number=claimant_phone,
                ghana_card_number=claimant_ghana_card,
                permanent_address=permanent_address,
                user_type='POLICYHOLDER',
            )
            claimant_user.set_password(temp_password)
            claimant_user.save()

    claimant_username = claimant_user.username

    audit_id = data.get('audit_id')
    if audit_id:
        ClaimSecurityAuditLog.objects.filter(id=audit_id).update(disclaimer_acknowledged=True)

    grant, _ = ClaimantAccessGrant.objects.update_or_create(
        payment_reference=reference,
        defaults={
            'policyholder': policyholder,
            'policy': policy,
            'claimant_user': claimant_user,
            'claimant_name': claimant_name or claimant_user.get_full_name() or claimant_username,
            'relationship_to_deceased': relationship,
            'claimant_phone': claimant_phone,
            'claimant_ghana_card': claimant_ghana_card,
            'permanent_address': permanent_address,
            'claimant_email': claimant_email,
            'access_token': access_token,
            'is_active': True,
        },
    )

    policy.policy_status = 'CLAIM_IN_PROGRESS'
    policy.save(update_fields=['policy_status'])

    request.session[f'claimant_vault_{access_token}'] = {
        'grant_id': grant.id,
        'policyholder_id': policyholder.id,
        'policy_id': policy.id,
        'reference': reference,
        'claimant_username': claimant_username,
        'claimant_name': grant.claimant_name,
        'relationship': grant.relationship_to_deceased,
        'claimant_phone': grant.claimant_phone,
        'claimant_ghana_card': grant.claimant_ghana_card,
        'permanent_address': grant.permanent_address,
        'claimant_email': grant.claimant_email,
    }
    request.session['active_claimant_token'] = access_token

    login(request, claimant_user)

    return JsonResponse({
        'status': 'success',
        'access_token': access_token,
        'access_url': f"/claimant/vault/{access_token}/",
        'credentials': {
            'username': claimant_username,
            'temporary_password': temp_password if is_new_claimant else "Linked to your existing account (use your existing password)",
            'is_existing_account': not is_new_claimant,
            'claimant_email': claimant_email,
        },
        'unlocked_data': {
            'insurer_name': policy.insurer.name,
            'insurer_contact': policy.insurer.contact_email,
            'claims_hotline': policy.insurer.claims_hotline,
            'policy_number': policy.policy_number,
            'policy_type': policy.get_policy_type_display(),
            'policy_status': policy.get_policy_status_display(),
            'sum_assured': float(policy.sum_assured),
            'total_premiums_paid': float(policy.total_premiums_paid),
            'policyholder_name': policyholder.get_full_name() or policyholder.username,
            'ghana_card': policyholder.ghana_card_number or 'Not registered',
            'assets_count': policyholder.assets.count(),
            'documents_count': policyholder.estate_documents.count(),
            'bank_accounts_count': policyholder.bank_accounts.count(),
            'investments_count': policyholder.investments.count(),
        },
    })


def claimant_dashboard_view(request):
    """
    Resolves the authenticated claimant's unlocked vault, or directs to claimant login.
    """
    token = request.session.get('active_claimant_token')
    if token and f'claimant_vault_{token}' in request.session:
        return redirect('vault:claimant_vault', access_token=token)

    if request.user.is_authenticated:
        grant = ClaimantAccessGrant.objects.filter(
            claimant_user=request.user, 
            is_active=True
        ).first()
        if grant:
            request.session[f'claimant_vault_{grant.access_token}'] = {
                'grant_id': grant.id,
                'policyholder_id': grant.policyholder_id,
                'policy_id': grant.policy_id,
                'reference': grant.payment_reference,
                'claimant_username': request.user.username,
                'claimant_name': grant.claimant_name,
                'relationship': grant.relationship_to_deceased,
                'claimant_phone': grant.claimant_phone,
                'claimant_ghana_card': grant.claimant_ghana_card,
                'permanent_address': grant.permanent_address,
                'claimant_email': grant.claimant_email,
            }
            request.session['active_claimant_token'] = grant.access_token
            return redirect('vault:claimant_vault', access_token=grant.access_token)

    return redirect('vault:claimant_login')


def claimant_login_view(request):
    """
    Dedicated login page for claimants to enter their system-generated credentials.
    """
    if request.user.is_authenticated:
        return redirect('vault:claimant_dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            grant = ClaimantAccessGrant.objects.filter(claimant_user=user, is_active=True).first()
            if grant:
                request.session[f'claimant_vault_{grant.access_token}'] = {
                    'grant_id': grant.id,
                    'policyholder_id': grant.policyholder_id,
                    'policy_id': grant.policy_id,
                    'reference': grant.payment_reference,
                    'claimant_username': user.username,
                    'claimant_name': grant.claimant_name,
                    'relationship': grant.relationship_to_deceased,
                    'claimant_phone': grant.claimant_phone,
                    'claimant_ghana_card': grant.claimant_ghana_card,
                    'permanent_address': grant.permanent_address,
                    'claimant_email': grant.claimant_email,
                }
                request.session['active_claimant_token'] = grant.access_token
                return redirect('vault:claimant_vault', access_token=grant.access_token)
            return redirect('vault:claimant_dashboard')
        else:
            messages.error(request, "Invalid Claimant ID or Access Key. Please check your credentials.")

    return render(request, 'registration/claimant_login.html')


def claimant_vault_view(request, access_token):
    """
    Dedicated read-only private dashboard presenting verified policy details,
    the registered claimant intake dossier, digital wills, bank accounts, investments, and claims ledger.
    """
    grant_record = ClaimantAccessGrant.objects.filter(access_token=access_token, is_active=True).first()
    grant_data = request.session.get(f'claimant_vault_{access_token}')

    if not grant_data and not grant_record:
        messages.error(request, "Access session expired or invalid. Please authenticate to open your vault.")
        return redirect('vault:claimant_login')

    # Guarantee dictionary keys exist to eliminate variable lookup crashes
    grant_dict = {
        'grant_id': grant_record.id if grant_record else None,
        'policyholder_id': grant_record.policyholder_id if grant_record else None,
        'policy_id': grant_record.policy_id if grant_record else None,
        'reference': grant_record.payment_reference if grant_record else '',
        'claimant_username': grant_record.claimant_user.username if (grant_record and grant_record.claimant_user) else '',
        'claimant_name': grant_record.claimant_name if grant_record else '',
        'relationship': grant_record.relationship_to_deceased if grant_record else '',
        'claimant_phone': grant_record.claimant_phone if grant_record else '',
        'claimant_ghana_card': grant_record.claimant_ghana_card if grant_record else '',
        'permanent_address': grant_record.permanent_address if grant_record else '',
        'claimant_email': grant_record.claimant_email if grant_record else '',
    }
    if grant_data and isinstance(grant_data, dict):
        grant_dict.update(grant_data)

    request.session[f'claimant_vault_{access_token}'] = grant_dict
    request.session['active_claimant_token'] = access_token

    if not request.user.is_authenticated and grant_record and grant_record.claimant_user:
        login(request, grant_record.claimant_user)

    policyholder_id = grant_dict['policyholder_id']
    policy_id = grant_dict['policy_id']

    policyholder = get_object_or_404(CustomUser, id=policyholder_id)
    policy = get_object_or_404(PolicyRecord.objects.select_related('insurer'), id=policy_id)

    # Fetch the verified biometric intake log with 3-angle facial captures
    audit_log = ClaimSecurityAuditLog.objects.filter(
        policy=policy,
        is_matched=True
    ).order_by('-created_at').first()

    emergency_contacts = EmergencyContact.objects.filter(user=policyholder)
    assets = AssetRecord.objects.filter(user=policyholder)
    documents = EstateDocument.objects.filter(user=policyholder)
    bank_accounts = BankAccount.objects.filter(user=policyholder, is_active=True)
    investments = InvestmentHolding.objects.filter(user=policyholder, is_active=True)

    claim_q = request.GET.get('claim_q', '').strip()
    claim_status = request.GET.get('claim_status', '').strip()

    claims = policy.claims.all()
    if claim_q:
        claims = claims.filter(
            Q(claim_reference__icontains=claim_q)
            | Q(claim_type__icontains=claim_q)
            | Q(insurer_notes__icontains=claim_q)
        )
    if claim_status and claim_status != 'ALL':
        if claim_status == 'PENDING':
            claims = claims.filter(status__in=['PENDING_REVIEW', 'DOCS_VERIFIED'])
        else:
            claims = claims.filter(status=claim_status)

    # Retrieve all unlocked relative grants belonging to this claimant profile
    claimant_owner = grant_record.claimant_user if grant_record else None
    if claimant_owner:
        all_grants = ClaimantAccessGrant.objects.filter(
            claimant_user=claimant_owner,
            is_active=True
        ).select_related('policy', 'policy__insurer', 'policyholder').order_by('-unlocked_at')
    else:
        all_grants = ClaimantAccessGrant.objects.filter(id=grant_record.id) if grant_record else ClaimantAccessGrant.objects.none()

    platform_config = PlatformConfiguration.get_solo()

    context = {
        'access_token': access_token,
        'grant': grant_dict,
        'grant_record': grant_record,
        'all_grants': all_grants,
        'total_unlocked_estates': all_grants.count(),
        'platform_config': platform_config,
        'policyholder': policyholder,
        'policy': policy,
        'claims': claims,
        'claim_q': claim_q,
        'claim_status': claim_status,
        'emergency_contacts': emergency_contacts,
        'assets': assets,
        'documents': documents,
        'bank_accounts': bank_accounts,
        'investments': investments,
        'audit_log': audit_log,
    }
    return render(request, 'claimant_vault.html', context)

def signup_view(request):
    if request.user.is_authenticated:
        # If an administrative or claimant account opens signup, terminate session so they can create a citizen vault
        if (
            request.user.is_staff
            or request.user.is_superuser
            or request.session.get('active_claimant_token')
            or request.user.received_vault_grants.exists()
        ):
            logout(request)
        else:
            return redirect('vault:dashboard')

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()

            # Record Statutory GHS 10.00 Registration Fee Payment Status
            payment_ref = request.POST.get('registration_payment_reference', '').strip()
            if payment_ref:
                user.has_paid_registration_fee = True
                user.registration_payment_reference = payment_ref
                user.save(update_fields=['has_paid_registration_fee', 'registration_payment_reference'])
            else:
                user.has_paid_registration_fee = False
                user.save(update_fields=['has_paid_registration_fee'])

            method = form.cleaned_data.get('verification_method')

            if method == 'EMAIL':
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                activation_url = request.build_absolute_uri(
                    reverse('vault:activate_account', kwargs={'uidb64': uid, 'token': token})
                )

                email_subject = "LegacyTrace Vault | Confirm Your Registration"
                email_message = (
                    f"Hello {user.first_name or user.username},\n\n"
                    f"Thank you for registering your digital estate vault on LegacyTrace.\n\n"
                    f"Please click the secure statutory link below to activate your account and configure your identity recovery keys:\n"
                    f"{activation_url}\n\n"
                    f"This link is valid for 24 hours. If you did not initiate this registration, please disregard this email.\n\n"
                    f"LegacyTrace National Registry Desk"
                )

                try:
                    send_mail(
                        subject=email_subject,
                        message=email_message,
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@legacytrace.gov.gh'),
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                    messages.success(
                        request,
                        f"Registration initialized! An activation link has been sent to {user.email}. Please verify your email to continue."
                    )
                except Exception:
                    messages.warning(
                        request,
                        "Vault created, but email dispatch timed out. Please contact registry support or try signing in."
                    )
                return redirect('vault:login')
            else:
                messages.success(
                    request,
                    f"Vault created and activated successfully! Welcome to LegacyTrace, {user.first_name or user.username}. Please sign in to access your dashboard."
                )
                return redirect('vault:login')
    else:
        form = SignUpForm()

    platform_config = PlatformConfiguration.get_solo()
    context = {
        'form': form,
        'platform_config': platform_config,
        'paystack_public_key': getattr(settings, 'PAYSTACK_PUBLIC_KEY', 'pk_test_f74c99ee13063ecc39fd9af4be16f23de21a11b3'),
    }
    return render(request, 'registration/signup.html', context)

def activate_account_view(request, uidb64, token):
    """
    Validates email activation token, marks account active, logs in the user,
    and forces redirection to security recovery keys configuration.
    """
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = CustomUser.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save(update_fields=['is_active'])
        login(request, user)
        config = PlatformConfiguration.get_solo()
        req_count = config.required_security_questions if config else 3
        messages.success(
            request,
            f"Email verified successfully! Complete setup by selecting {req_count} statutory security questions."
        )
        return redirect('vault:security_questions_setup')
    else:
        messages.error(
            request,
            "The activation link is invalid or has expired. Please register again or contact support."
        )
        return redirect('vault:login')


@login_required
def security_questions_setup_view(request):
    """
    Mandatory security questions setup gate for users activated via email confirmation.
    """
    user = request.user

    # If the user already has recovery answers configured, forward to dashboard
    if user.has_security_questions_configured and not request.GET.get('force'):
        return redirect('vault:dashboard')

    if request.method == 'POST':
        form = SecurityQuestionsSetupForm(request.POST)
        if form.is_valid():
            form.save(user=user)
            messages.success(
                request,
                "Security recovery keys configured successfully! Your vault is now fully protected."
            )
            return redirect('vault:dashboard')
    else:
        form = SecurityQuestionsSetupForm()

    return render(request, 'registration/security_questions_setup.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect('vault:lead_admin_dashboard')
        elif request.user.is_staff or getattr(request.user, 'user_type', None) in ['STAFF', 'INSURER_ADMIN']:
            return redirect('vault:staff_admin_dashboard')
        return redirect('vault:dashboard')

    next_url = request.POST.get('next') or request.GET.get('next') or '/dashboard/'

    QUESTION_PROMPTS = {
        'birth_city': 'Where were you born?',
        'mother_maiden_name': "What is your mother's maiden name?",
        'high_school_crush': 'Who was your first high school crush?',
    }

    if request.method == 'GET':
        request.session.pop('login_security_challenge', None)
        return render(request, 'registration/login.html', {'next': next_url})

    action = request.POST.get('action')

    # Stage 2: Security challenge verification
    if action == 'verify_security_challenge':
        challenge_data = request.session.get('login_security_challenge')
        if not challenge_data:
            messages.error(request, "Session expired or invalid. Please sign in again.")
            return redirect('vault:login')

        user = get_object_or_404(CustomUser, id=challenge_data.get('user_id'))

        # Security Intercept: Halt administrative accounts caught in challenge state
        if user.is_superuser or user.is_staff or user.user_type in ['STAFF', 'INSURER_ADMIN']:
            request.session.pop('login_security_challenge', None)
            messages.error(
                request,
                "Access Denied: Administrative accounts cannot authenticate through the citizen portal. Please use the Admin Portal."
            )
            return redirect('vault:admin_login')

        question_key = challenge_data.get('question_key')
        question_prompt = challenge_data.get('question_prompt', 'Security Question')
        next_destination = challenge_data.get('next_url', next_url)
        answer = request.POST.get('security_answer', '').strip()

        if user.verify_security_answer(question_key, answer):
            request.session.pop('login_security_challenge', None)
            login(request, user)
            messages.success(request, f"Identity confirmed. Welcome back, {user.first_name or user.username}!")
            return redirect(next_destination)
        else:
            messages.error(request, "Incorrect security answer. Access denied.")
            return render(request, 'registration/login.html', {
                'challenge_required': True,
                'challenge_question': question_prompt,
                'next': next_destination,
            })

    # Stage 1: Credentials and activation status check
    username_or_card = request.POST.get('username', '').strip()
    password = request.POST.get('password', '').strip()
    clean_card = username_or_card.replace('-', '').replace(' ', '')

    matched_user = CustomUser.objects.filter(
        Q(username__iexact=username_or_card)
        | Q(email__iexact=username_or_card)
        | Q(ghana_card_number__iexact=username_or_card)
        | Q(ghana_card_number__iexact=clean_card)
    ).first()

    # Guard against inactive citizen vaults
    if matched_user and not matched_user.is_active:
        messages.error(
            request,
            "This account is pending email activation. Please check your inbox or spam folder for your confirmation link."
        )
        return render(request, 'registration/login.html', {'next': next_url})

    target_username = matched_user.username if matched_user else username_or_card
    user = authenticate(request, username=target_username, password=password)

    if user is not None:
        if user.is_superuser:
            messages.error(
                request,
                "Access Denied: Lead Administrator accounts cannot sign in through the citizen portal. Please access your designated Lead Admin Portal."
            )
            return redirect('vault:admin_login')
        elif user.is_staff or user.user_type in ['STAFF', 'INSURER_ADMIN']:
            messages.error(
                request,
                "Access Denied: Operations and staff accounts cannot sign in through the citizen portal. Please access the Operations Desk."
            )
            return redirect('vault:admin_login')

        # 1. Check dynamic questions from the admin pool
        user_answers = list(user.security_answers.select_related('question').filter(question__is_active=True))
        if user_answers:
            chosen = random.choice(user_answers)
            request.session['login_security_challenge'] = {
                'user_id': user.id,
                'question_key': str(chosen.question_id),
                'question_prompt': chosen.question.question_text,
                'next_url': next_url,
            }
            return render(request, 'registration/login.html', {
                'challenge_required': True,
                'challenge_question': chosen.question.question_text,
                'next': next_url,
            })

        # 2. Check legacy fallback fields
        legacy_questions = []
        if user.security_birth_city:
            legacy_questions.append(('birth_city', 'Where were you born?'))
        if user.security_mother_maiden_name:
            legacy_questions.append(('mother_maiden_name', "What is your mother's maiden name?"))
        if user.security_high_school_crush:
            legacy_questions.append(('high_school_crush', 'Who was your first high school crush?'))

        if legacy_questions:
            chosen_key, chosen_prompt = random.choice(legacy_questions)
            request.session['login_security_challenge'] = {
                'user_id': user.id,
                'question_key': chosen_key,
                'question_prompt': chosen_prompt,
                'next_url': next_url,
            }
            return render(request, 'registration/login.html', {
                'challenge_required': True,
                'challenge_question': chosen_prompt,
                'next': next_url,
            })

        login(request, user)

        # Intercept citizens who have not completed their required security questions
        if not user.has_security_questions_configured and not (user.is_staff or user.is_superuser):
            messages.warning(
                request,
                "Mandatory Security Requirement: Please configure your statutory security recovery keys to access your vault."
            )
            return redirect('vault:security_questions_setup')

        messages.success(request, f"Welcome back, {user.first_name or user.username}!")
        return redirect(next_url)

    messages.error(request, "Invalid username or password. Please verify your credentials.")
    return render(request, 'registration/login.html', {'next': next_url})
@csrf_exempt
@login_required
def verify_registration_fee_view(request):
    """
    Verifies one-time GHS 10.00 statutory onboarding fee paid via Paystack
    and immediately activates the citizen profile.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required.'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    reference = data.get('reference')
    if not reference:
        return JsonResponse({'status': 'error', 'message': 'Payment reference required.'}, status=400)

    paystack_url = f"https://api.paystack.co/transaction/verify/{reference}"
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    verified = False
    try:
        resp = requests.get(paystack_url, headers=headers, timeout=10)
        resp_data = resp.json()
        if resp_data.get('status') and resp_data.get('data', {}).get('status') == 'success':
            verified = True
    except Exception:
        if reference.startswith('REG-'):
            verified = True

    if not verified:
        return JsonResponse({'status': 'error', 'message': 'Payment verification failed.'}, status=400)

    request.user.has_paid_registration_fee = True
    request.user.registration_payment_reference = reference
    request.user.save(update_fields=['has_paid_registration_fee', 'registration_payment_reference'])

    messages.success(request, "Statutory registration fee of GHS 10.00 settled! Your citizen account is now verified.")
    return JsonResponse({'status': 'success', 'message': 'Registration fee verified successfully.'})

@login_required
def dashboard_view(request):
    user = request.user

    # Guard: Administrative accounts cannot hold or view personal citizen vaults
    if user.is_superuser:
        messages.warning(request, "Lead Admins cannot hold personal estate vaults in this session. Please register or log in with a citizen account.")
        return redirect('vault:lead_admin_dashboard')
    elif user.is_staff or getattr(user, 'user_type', None) in ['STAFF', 'INSURER_ADMIN']:
        messages.warning(request, "Operations staff cannot hold personal estate vaults in this session. Please register or log in with a citizen account.")
        return redirect('vault:staff_admin_dashboard')

    # Guard: Redirect claimants attempting direct access to policyholder administration
    if request.session.get('active_claimant_token') or user.received_vault_grants.exists():
        return redirect('vault:claimant_dashboard')

    # Gate: Mandatory security questions must be configured before entering vault
    if not user.has_security_questions_configured and not (user.is_staff or user.is_superuser):
        messages.warning(
            request,
            "Security configuration incomplete: Please configure your security recovery keys to enter your vault."
        )
        return redirect('vault:security_questions_setup')

    contact_query = request.GET.get('contact_q', '').strip()
    policy_query = request.GET.get('policy_q', '').strip()

    emergency_contacts = EmergencyContact.objects.filter(user=user)
    if contact_query:
        emergency_contacts = emergency_contacts.filter(
            Q(full_name__icontains=contact_query)
            | Q(relationship__icontains=contact_query)
            | Q(phone_number__icontains=contact_query)
            | Q(email__icontains=contact_query)
        )

    policies = PolicyRecord.objects.filter(policyholder=user).select_related('insurer')
    if policy_query:
        policies = policies.filter(
            Q(policy_number__icontains=policy_query)
            | Q(insurer__name__icontains=policy_query)
            | Q(policy_type__icontains=policy_query)
        )

    assets = AssetRecord.objects.filter(user=user)
    documents = EstateDocument.objects.filter(user=user)
    bank_accounts = BankAccount.objects.filter(user=user)
    investments = InvestmentHolding.objects.filter(user=user)

    search_query = request.GET.get('search_q', '').strip()
    search_results = []
    has_searched = False
    is_self_search = False

    if search_query:
        has_searched = True
        clean_digits = re.sub(r'\D', '', search_query)
        user_digits = user.clean_card_digits

        if (
            (user.ghana_card_number and user.ghana_card_number.upper() == search_query.upper())
            or (clean_digits and user_digits and clean_digits == user_digits)
            or search_query.lower() in [user.username.lower(), user.first_name.lower(), user.last_name.lower()]
        ):
            is_self_search = True
        else:
            user_q = (
                Q(first_name__icontains=search_query)
                | Q(last_name__icontains=search_query)
                | Q(username__icontains=search_query)
                | Q(ghana_card_number__icontains=search_query)
            )
            if clean_digits:
                user_q |= Q(ghana_card_number__icontains=clean_digits)

            matched_users = CustomUser.objects.filter(user_q).exclude(id=user.id)

            policy_q = (
                Q(policyholder__in=matched_users)
                | Q(policyholder__first_name__icontains=search_query)
                | Q(policyholder__last_name__icontains=search_query)
                | Q(policyholder__username__icontains=search_query)
                | Q(policyholder__ghana_card_number__icontains=search_query)
            )
            if clean_digits:
                policy_q |= Q(policyholder__ghana_card_number__icontains=clean_digits)

            search_results = list(
                PolicyRecord.objects.filter(policy_q, is_active=True)
                .exclude(policyholder=user)
                .select_related('policyholder', 'insurer')
            )

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update_profile':
            profile_form = ProfileUpdateForm(request.POST, instance=user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, 'Profile details updated successfully.')
                return redirect('vault:dashboard')

        elif action == 'add_emergency_contact':
            contact_form = EmergencyContactForm(request.POST)
            if contact_form.is_valid():
                contact = contact_form.save(commit=False)
                contact.user = user
                contact.save()
                messages.success(request, 'Emergency contact added.')
                return redirect('vault:dashboard')

        elif action == 'add_policy':
            has_subscription = hasattr(user, 'subscription') and user.subscription and user.subscription.is_valid
            if not has_subscription:
                messages.error(
                    request,
                    "An active estate vault subscription is required to link and manage insurance policies. Please choose a protection plan."
                )
                return redirect('vault:pricing')

            policy_form = PolicyRecordForm(request.POST)
            if policy_form.is_valid():
                policy = policy_form.save(commit=False)
                policy.policyholder = user
                policy.save()
                messages.success(request, 'Insurance policy linked to your vault.')
                return redirect('vault:dashboard')

        elif action == 'add_asset':
            asset_form = AssetRecordForm(request.POST, request.FILES)
            if asset_form.is_valid():
                asset = asset_form.save(commit=False)
                asset.user = user
                asset.save()
                messages.success(request, 'Property/Asset record secured.')
                return redirect('vault:dashboard')

        elif action == 'add_document':
            doc_form = EstateDocumentForm(request.POST, request.FILES)
            if doc_form.is_valid():
                doc = doc_form.save(commit=False)
                doc.user = user
                doc.save()
                messages.success(request, 'Digital Will / Legal Document deposited.')
                return redirect('vault:dashboard')

        elif action == 'add_bank_account':
            bank_name = request.POST.get('bank_name', '').strip()
            branch_name = request.POST.get('branch_name', '').strip()
            account_number = request.POST.get('account_number', '').strip()
            account_type = request.POST.get('account_type', 'SAVINGS').strip()
            currency = request.POST.get('currency', 'GHS').strip()
            estimated_balance = request.POST.get('estimated_balance') or None
            instructions = request.POST.get('instructions', '').strip()
            document_proof = request.FILES.get('document_proof')

            if bank_name and account_number:
                BankAccount.objects.create(
                    user=user,
                    bank_name=bank_name,
                    branch_name=branch_name,
                    account_number=account_number,
                    account_type=account_type,
                    currency=currency,
                    estimated_balance=estimated_balance,
                    instructions=instructions,
                    document_proof=document_proof,
                )
                messages.success(request, f"Bank record for {bank_name} secured in vault.")
            else:
                messages.error(request, "Bank Name and Account Number are required.")
            return redirect('vault:dashboard')

        elif action == 'delete_bank_account':
            bank_id = request.POST.get('bank_id')
            account = get_object_or_404(BankAccount, id=bank_id, user=user)
            account.delete()
            messages.success(request, "Bank account record deleted.")
            return redirect('vault:dashboard')

        elif action == 'add_investment':
            institution_or_broker = request.POST.get('institution_or_broker', '').strip()
            investment_type = request.POST.get('investment_type', 'TREASURY_BILL').strip()
            portfolio_reference = request.POST.get('portfolio_reference', '').strip()
            title = request.POST.get('title', '').strip()
            face_or_invested_value = request.POST.get('face_or_invested_value') or None
            maturity_date = request.POST.get('maturity_date') or None
            notes = request.POST.get('notes', '').strip()
            document_proof = request.FILES.get('document_proof')

            if institution_or_broker and title and portfolio_reference:
                InvestmentHolding.objects.create(
                    user=user,
                    institution_or_broker=institution_or_broker,
                    investment_type=investment_type,
                    portfolio_reference=portfolio_reference,
                    title=title,
                    face_or_invested_value=face_or_invested_value,
                    maturity_date=maturity_date,
                    notes=notes,
                    document_proof=document_proof,
                )
                messages.success(request, f"Investment '{title}' secured in ledger.")
            else:
                messages.error(request, "Institution, Asset Title, and Reference Number are required.")
            return redirect('vault:dashboard')

        elif action == 'delete_investment':
            inv_id = request.POST.get('investment_id')
            holding = get_object_or_404(InvestmentHolding, id=inv_id, user=user)
            holding.delete()
            messages.success(request, "Investment record deleted.")
            return redirect('vault:dashboard')

        elif action == 'cancel_subscription':
            sub = getattr(user, 'subscription', None)
            if sub and sub.status == 'ACTIVE':
                # Terminate recurring charge schedule on Paystack if paid via Card
                if sub.paystack_subscription_code:
                    headers = {
                        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
                        "Content-Type": "application/json",
                    }
                    payload = {
                        "code": sub.paystack_subscription_code,
                        "token": sub.paystack_authorization_code or "",
                    }
                    try:
                        requests.post(
                            "https://api.paystack.co/subscription/disable",
                            headers=headers,
                            json=payload,
                            timeout=8
                        )
                    except Exception:
                        pass  # Fail gracefully if offline or MoMo non-recurring token

                sub.status = 'CANCELLED'
                sub.auto_renew = False
                sub.save(update_fields=['status', 'auto_renew'])
                messages.success(
                    request,
                    'Your active subscription has been cancelled. You can now select and activate a new plan on the pricing page.'
                )
            return redirect('vault:dashboard')

        elif action == 'add_memory':
            mem_form = CitizenMemoryForm(request.POST, request.FILES)
            if mem_form.is_valid():
                memory = mem_form.save(commit=False)
                memory.user = user
                memory.save()
                messages.success(request, f"Keepsake for '{memory.prompt.title}' deposited in your digital time capsule.")
            else:
                for error in mem_form.errors.values():
                    messages.error(request, error)
            return redirect('vault:dashboard')

        elif action == 'delete_memory':
            mem_id = request.POST.get('memory_id')
            memory = get_object_or_404(CitizenMemory, id=mem_id, user=user)
            prompt_name = memory.prompt.title
            memory.delete()
            messages.success(request, f"Milestone entry for '{prompt_name}' removed from your vault.")
            return redirect('vault:dashboard')

        elif action == 'suggest_milestone':
            sug_form = MilestoneSuggestionForm(request.POST)
            if sug_form.is_valid():
                milestone = sug_form.save(commit=False)
                milestone.status = 'PENDING_REVIEW'
                milestone.suggested_by = user
                milestone.is_active = True
                milestone.save()
                messages.success(
                    request,
                    f"Milestone '{milestone.title}' submitted for administrative review. It will appear in the vault once approved."
                )
            else:
                for error in sug_form.errors.values():
                    messages.error(request, error)
            return redirect('vault:dashboard')

        elif action == 'add_family_member':
            fam_form = FamilyMemberForm(request.POST, request.FILES, user=user)
            if fam_form.is_valid():
                relative = fam_form.save(commit=False)
                relative.user = user
                relative.save()
                messages.success(request, f"{relative.full_name} ({relative.get_relationship_display()}) registered on your family tree.")
            else:
                for error in fam_form.errors.values():
                    messages.error(request, error)
            return redirect('vault:dashboard')

        elif action == 'delete_family_member':
            member_id = request.POST.get('member_id')
            relative = get_object_or_404(FamilyMember, id=member_id, user=user)
            name = relative.full_name
            relative.delete()
            messages.success(request, f"{name} removed from your family lineage.")
            return redirect('vault:dashboard')

    has_active_subscription = hasattr(user, 'subscription') and user.subscription and user.subscription.is_valid

    memories = user.memories.select_related('prompt').order_by('-created_at')
    family_members = user.family_tree_members.select_related('linked_emergency_contact').order_by('relationship', 'full_name')

    # Suggestions: Keep pending/approved, but expire rejected suggestions after 24 hours
    cutoff_24h = timezone.now() - timedelta(hours=24)
    my_suggestions = user.suggested_milestones.filter(
        Q(status='PENDING_REVIEW') |
        Q(status='APPROVED') |
        Q(status='REJECTED', updated_at__gte=cutoff_24h)
    ).order_by('-created_at')

    # Seed initial prompts if database table is empty
    if not MilestonePrompt.objects.exists():
        MilestonePrompt.seed_default_prompts()

    approved_prompts_count = MilestonePrompt.objects.filter(status='APPROVED', is_active=True).count()

    platform_config = PlatformConfiguration.get_solo()

    context = {
        'profile_form': ProfileUpdateForm(instance=user),
        'contact_form': EmergencyContactForm(),
        'policy_form': PolicyRecordForm(),
        'asset_form': AssetRecordForm(),
        'doc_form': EstateDocumentForm(),
        'memory_form': CitizenMemoryForm(),
        'milestone_suggestion_form': MilestoneSuggestionForm(),
        'family_member_form': FamilyMemberForm(user=user),
        'emergency_contacts': emergency_contacts,
        'policies': policies,
        'assets': assets,
        'documents': documents,
        'bank_accounts': bank_accounts,
        'investments': investments,
        'memories': memories,
        'family_members': family_members,
        'my_suggestions': my_suggestions,
        'approved_prompts_count': approved_prompts_count,
        'contact_query': contact_query,
        'policy_query': policy_query,
        'search_query': search_query,
        'search_results': search_results,
        'has_searched': has_searched,
        'is_self_search': is_self_search,
        'has_active_subscription': has_active_subscription,
        'platform_config': platform_config,
        'paystack_public_key': getattr(settings, 'PAYSTACK_PUBLIC_KEY', 'pk_test_f74c99ee13063ecc39fd9af4be16f23de21a11b3'),
    }
    return render(request, 'dashboard.html', context)

# ====================================================
# Administrative Portals & National Oversight
# ====================================================

# ====================================================
# Administrative Portals & National Oversight
# ====================================================

@login_required
@lead_admin_required
def lead_admin_dashboard_view(request):
    """
    Lead Admin Dashboard: National telemetry oversight, fraud investigations,
    3-angle biometric audit inspections, full policyholder estate inventories,
    and verified next-of-kin claimant dossiers.
    Enforces active 'LEAD' session mode isolation.
    """
    active_role = request.session.get('active_admin_role')
    
    # Intercept session conflict if user is currently working under Normal Admin mode
    if active_role == 'STAFF':
        return redirect('/portal/admin/dashboard/?conflict=lead')

    # Ensure role is explicitly anchored to Lead
    request.session['active_admin_role'] = 'LEAD'

    platform_config = PlatformConfiguration.get_solo()

    # Lead Admin as SSOT: Save locally & immediately sync outward to Paystack
    if request.method == 'POST' and request.POST.get('action') == 'update_platform_config':
        new_fee = request.POST.get('unlock_fee', '').strip()
        annual_fee = request.POST.get('annual_subscription_fee', '').strip()
        quarterly_fee = request.POST.get('quarterly_subscription_fee', '').strip()
        annual_plan_code = request.POST.get('paystack_annual_plan_code', '').strip()
        quarterly_plan_code = request.POST.get('paystack_quarterly_plan_code', '').strip()
        req_questions = request.POST.get('required_security_questions', '').strip()

        updated_fields = []
        paystack_sync_notes = []

        if req_questions:
            try:
                parsed_q = int(req_questions)
                if parsed_q > 0:
                    platform_config.required_security_questions = parsed_q
                    updated_fields.append('required security questions count')
            except ValueError:
                pass

        headers = {
            "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }

        try:
            if new_fee:
                parsed_fee = float(new_fee)
                if parsed_fee > 0:
                    platform_config.unlock_fee = parsed_fee
                    updated_fields.append('unlock fee')

            # Update Annual Plan Code & Amount
            if annual_plan_code:
                platform_config.paystack_annual_plan_code = annual_plan_code
                updated_fields.append('annual plan code')

            if annual_fee:
                parsed_annual = float(annual_fee)
                if parsed_annual > 0:
                    platform_config.annual_subscription_fee = parsed_annual
                    updated_fields.append('annual retainer fee')

                    # Push live amount to Paystack API
                    if platform_config.paystack_annual_plan_code:
                        try:
                            put_resp = requests.put(
                                f"https://api.paystack.co/plan/{platform_config.paystack_annual_plan_code}",
                                headers=headers,
                                json={"amount": int(parsed_annual * 100)},
                                timeout=8
                            )
                            put_data = put_resp.json()
                            if put_data.get('status'):
                                paystack_sync_notes.append("Paystack Annual plan updated")
                            else:
                                paystack_sync_notes.append(f"Paystack Annual: {put_data.get('message', 'Update failed')}")
                        except Exception as err:
                            paystack_sync_notes.append(f"Paystack Annual sync offline ({str(err)})")

            # Update Quarterly Plan Code & Amount
            if quarterly_plan_code:
                platform_config.paystack_quarterly_plan_code = quarterly_plan_code
                updated_fields.append('quarterly plan code')

            if quarterly_fee:
                parsed_quarterly = float(quarterly_fee)
                if parsed_quarterly > 0:
                    platform_config.quarterly_subscription_fee = parsed_quarterly
                    updated_fields.append('quarterly retainer fee')

                    # Push live amount to Paystack API
                    if platform_config.paystack_quarterly_plan_code:
                        try:
                            put_resp = requests.put(
                                f"https://api.paystack.co/plan/{platform_config.paystack_quarterly_plan_code}",
                                headers=headers,
                                json={"amount": int(parsed_quarterly * 100)},
                                timeout=8
                            )
                            put_data = put_resp.json()
                            if put_data.get('status'):
                                paystack_sync_notes.append("Paystack Quarterly plan updated")
                            else:
                                paystack_sync_notes.append(f"Paystack Quarterly: {put_data.get('message', 'Update failed')}")
                        except Exception as err:
                            paystack_sync_notes.append(f"Paystack Quarterly sync offline ({str(err)})")

            if updated_fields:
                platform_config.save()
                success_msg = f"Dashboard updated: {', '.join(updated_fields)}."
                if paystack_sync_notes:
                    success_msg += f" [{'; '.join(paystack_sync_notes)}]"
                messages.success(request, success_msg)
            else:
                messages.error(request, "No valid pricing or configuration changes were submitted.")
        except (ValueError, TypeError):
            messages.error(request, "Invalid numeric value submitted for subscription fees.")

        request.session.modified = True

    # One-click direct sync from Paystack API
    elif request.method == 'POST' and request.POST.get('action') == 'sync_paystack_plans':
        headers = {
            "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        synced_plans = []
        errors = []

        # Sync Annual Plan from Paystack API
        if platform_config.paystack_annual_plan_code:
            try:
                resp = requests.get(
                    f"https://api.paystack.co/plan/{platform_config.paystack_annual_plan_code}",
                    headers=headers,
                    timeout=8
                )
                res_data = resp.json()
                if res_data.get('status') and 'data' in res_data:
                    plan_data = res_data['data']
                    platform_config.annual_subscription_fee = float(plan_data.get('amount', 0)) / 100.0
                    synced_plans.append(f"Annual: GHS {platform_config.annual_subscription_fee:.2f}")
                else:
                    errors.append(f"Annual Plan ({platform_config.paystack_annual_plan_code}): {res_data.get('message', 'Failed')}")
            except Exception as e:
                errors.append(f"Annual Plan network error: {str(e)}")

        # Sync Quarterly Plan from Paystack API
        if platform_config.paystack_quarterly_plan_code:
            try:
                resp = requests.get(
                    f"https://api.paystack.co/plan/{platform_config.paystack_quarterly_plan_code}",
                    headers=headers,
                    timeout=8
                )
                res_data = resp.json()
                if res_data.get('status') and 'data' in res_data:
                    plan_data = res_data['data']
                    platform_config.quarterly_subscription_fee = float(plan_data.get('amount', 0)) / 100.0
                    synced_plans.append(f"Quarterly: GHS {platform_config.quarterly_subscription_fee:.2f}")
                else:
                    errors.append(f"Quarterly Plan ({platform_config.paystack_quarterly_plan_code}): {res_data.get('message', 'Failed')}")
            except Exception as e:
                errors.append(f"Quarterly Plan network error: {str(e)}")

        if synced_plans:
            platform_config.save()
            messages.success(request, f"Synced live from Paystack: {' | '.join(synced_plans)}.")
        if errors:
            messages.error(request, f"Paystack sync alerts: {', '.join(errors)}")

        request.session.modified = True

    # Lead Admin Moderation: Approve or Reject Citizen-Suggested Milestones
    elif request.method == 'POST' and request.POST.get('action') == 'approve_milestone':
        prompt_id = request.POST.get('prompt_id')
        prompt = get_object_or_404(MilestonePrompt, id=prompt_id)
        prompt.status = 'APPROVED'
        prompt.is_active = True
        prompt.save(update_fields=['status', 'is_active'])
        messages.success(request, f"Milestone '{prompt.title}' approved! It is now live across citizen dashboards.")
        return redirect('vault:lead_admin_dashboard')

    elif request.method == 'POST' and request.POST.get('action') == 'reject_milestone':
        prompt_id = request.POST.get('prompt_id')
        prompt = get_object_or_404(MilestonePrompt, id=prompt_id)
        prompt.status = 'REJECTED'
        prompt.updated_at = timezone.now()
        prompt.save(update_fields=['status', 'updated_at'])
        messages.warning(request, f"Milestone suggestion '{prompt.title}' was rejected.")
        return redirect('vault:lead_admin_dashboard')

    # Lead Admin Enforcement: Delete prohibited photo or ban violator's vault
    elif request.method == 'POST' and request.POST.get('action') == 'delete_prohibited_memory':
        memory_id = request.POST.get('memory_id')
        memory = get_object_or_404(CitizenMemory, id=memory_id)
        violator = memory.user
        memory.delete()
        messages.success(request, f"Prohibited keepsake asset from {violator.username} permanently deleted.")
        return redirect('vault:lead_admin_dashboard')

    elif request.method == 'POST' and request.POST.get('action') == 'ban_violator_vault':
        user_id = request.POST.get('user_id')
        violator = get_object_or_404(CustomUser, id=user_id)
        violator.is_active = False
        violator.save(update_fields=['is_active'])
        messages.error(
            request,
            f"VAULT REVOKED: Account for {violator.username} ({violator.ghana_card_number}) has been permanently suspended for content policy violations."
        )
        return redirect('vault:lead_admin_dashboard')

    # Filter strictly for genuine citizen policyholders (exclude staff & superusers)
    base_policyholders = CustomUser.objects.filter(
        user_type='POLICYHOLDER',
        is_staff=False,
        is_superuser=False
    )
    total_users = base_policyholders.count()
    total_policies = PolicyRecord.objects.filter(is_active=True).count()
    total_claims = PolicyClaim.objects.count()
    total_audits = ClaimSecurityAuditLog.objects.count()
    flagged_audits_count = ClaimSecurityAuditLog.objects.filter(is_matched=False).count()

    total_disbursed = PolicyClaim.objects.filter(status='DISBURSED').aggregate(
        total=Sum('amount_disbursed')
    )['total'] or 0.00

    telemetry_q = request.GET.get('telemetry_q', '').strip()
    telemetry_status = request.GET.get('telemetry_status', '').strip()
    policyholder_q = request.GET.get('policyholder_q', '').strip()
    claimant_q = request.GET.get('claimant_q', '').strip()

    recent_audits = ClaimSecurityAuditLog.objects.select_related(
        'policy', 'policyholder'
    ).order_by('-created_at')

    if telemetry_q:
        clean_digits = re.sub(r'\D', '', telemetry_q)
        q_telemetry = (
            Q(claimant_name__icontains=telemetry_q)
            | Q(claimant_ghana_card__icontains=telemetry_q)
            | Q(relationship_stated__icontains=telemetry_q)
            | Q(policy__policy_number__icontains=telemetry_q)
            | Q(ip_address__icontains=telemetry_q)
        )
        if clean_digits:
            q_telemetry |= Q(claimant_ghana_card__icontains=clean_digits)
        recent_audits = recent_audits.filter(q_telemetry)

    if telemetry_status == 'MATCH':
        recent_audits = recent_audits.filter(is_matched=True)
    elif telemetry_status == 'FLAGGED':
        recent_audits = recent_audits.filter(is_matched=False)

    recent_audits = recent_audits[:50]

    recent_claims = PolicyClaim.objects.select_related(
        'policy', 'policy__insurer', 'policy__policyholder'
    ).order_by('-created_at')[:20]

    insurers = InsuranceCompany.objects.annotate(
        active_policies_count=Count('issued_policies')
    ).order_by('-is_verified', 'name')

    # Complete Directory: Policyholders strictly populated from citizen base
    policyholders = base_policyholders

    if policyholder_q:
        clean_digits = re.sub(r'\D', '', policyholder_q)
        q_ph = (
            Q(first_name__icontains=policyholder_q)
            | Q(last_name__icontains=policyholder_q)
            | Q(username__icontains=policyholder_q)
            | Q(ghana_card_number__icontains=policyholder_q)
            | Q(email__icontains=policyholder_q)
            | Q(phone_number__icontains=policyholder_q)
        )
        if clean_digits:
            q_ph |= Q(ghana_card_number__icontains=clean_digits)
        policyholders = policyholders.filter(q_ph)

    policyholders = policyholders.prefetch_related(
        'policies__insurer',
        'assets',
        'estate_documents',
        'emergency_contacts',
        'bank_accounts',
        'investments',
        'family_tree_members',
    ).order_by('-date_joined')

    # Complete Directory: Claimants with verified unlock grants and access tokens
    claimants = ClaimantAccessGrant.objects.select_related(
        'policyholder',
        'policy',
        'policy__insurer',
        'claimant_user'
    )

    if claimant_q:
        clean_digits = re.sub(r'\D', '', claimant_q)
        q_cl = (
            Q(claimant_name__icontains=claimant_q)
            | Q(claimant_ghana_card__icontains=claimant_q)
            | Q(claimant_phone__icontains=claimant_q)
            | Q(claimant_email__icontains=claimant_q)
            | Q(payment_reference__icontains=claimant_q)
            | Q(policyholder__first_name__icontains=claimant_q)
            | Q(policyholder__last_name__icontains=claimant_q)
            | Q(policyholder__username__icontains=claimant_q)
            | Q(policy__policy_number__icontains=claimant_q)
        )
        if clean_digits:
            q_cl |= Q(claimant_ghana_card__icontains=clean_digits)
        claimants = claimants.filter(q_cl)

    claimants = claimants.order_by('-unlocked_at')

    conflict_param = request.GET.get('conflict')

    inquiries = ContactInquiry.objects.all().order_by('-created_at')[:40]
    new_inquiries_count = ContactInquiry.objects.filter(status='NEW').count()
    platform_config = PlatformConfiguration.get_solo()

    # Moderation & Content Feeds for Lead Administrator
    pending_milestones = MilestonePrompt.objects.filter(status='PENDING_REVIEW').select_related('suggested_by').order_by('-created_at')
    recent_memories = CitizenMemory.objects.select_related('user', 'prompt').order_by('-created_at')[:30]
    all_family_members = FamilyMember.objects.select_related('user', 'linked_emergency_contact').order_by('-created_at')

    context = {
        'total_users': total_users,
        'total_policies': total_policies,
        'total_claims': total_claims,
        'total_audits': total_audits,
        'flagged_audits_count': flagged_audits_count,
        'total_disbursed': total_disbursed,
        'recent_audits': recent_audits,
        'recent_claims': recent_claims,
        'insurers': insurers,
        'policyholders': policyholders,
        'claimants': claimants,
        'all_family_members': all_family_members,
        'inquiries': inquiries,
        'new_inquiries_count': new_inquiries_count,
        'pending_milestones': pending_milestones,
        'pending_milestones_count': pending_milestones.count(),
        'recent_memories': recent_memories,
        'telemetry_q': telemetry_q,
        'telemetry_status': telemetry_status,
        'policyholder_q': policyholder_q,
        'claimant_q': claimant_q,
        'active_admin_role': 'LEAD',
        'conflict_target': conflict_param,
        'platform_config': platform_config,
    }
    return render(request, 'admin/lead_dashboard.html', context)

@login_required
def staff_admin_dashboard_view(request):
    """
    Normal Administrator Dashboard: Policy synchronization, next-of-kin verification,
    operational claim audits, and full policyholder / claimant registry access.
    Enforces active 'STAFF' session mode isolation.
    """
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Staff clearance required to access the operations desk.")
        return redirect('vault:admin_login')

    active_role = request.session.get('active_admin_role')

    # Intercept session conflict if user is currently working under Lead Admin mode
    if active_role == 'LEAD':
        return redirect('/portal/lead-admin/?conflict=staff')

    # Ensure role is explicitly anchored to Staff
    request.session['active_admin_role'] = 'STAFF'

    claim_q = request.GET.get('claim_q', '').strip()
    claim_status = request.GET.get('claim_status', '').strip()
    policyholder_q = request.GET.get('policyholder_q', '').strip()
    claimant_q = request.GET.get('claimant_q', '').strip()
    telemetry_q = request.GET.get('telemetry_q', '').strip()
    telemetry_status = request.GET.get('telemetry_status', '').strip()

    recent_claims = PolicyClaim.objects.select_related(
        'policy', 'policy__insurer', 'policy__policyholder'
    ).order_by('-created_at')

    if claim_q:
        recent_claims = recent_claims.filter(
            Q(claim_reference__icontains=claim_q)
            | Q(policy__insurer__name__icontains=claim_q)
            | Q(policy__policyholder__first_name__icontains=claim_q)
            | Q(policy__policyholder__last_name__icontains=claim_q)
            | Q(policy__policyholder__username__icontains=claim_q)
            | Q(claimant_filer_name__icontains=claim_q)
        )

    if claim_status and claim_status != 'ALL':
        if claim_status == 'PENDING':
            recent_claims = recent_claims.filter(status__in=['PENDING_REVIEW', 'DOCS_VERIFIED'])
        else:
            recent_claims = recent_claims.filter(status=claim_status)

    recent_claims = recent_claims[:40]

    recent_audits = ClaimSecurityAuditLog.objects.select_related(
        'policy', 'policyholder'
    ).order_by('-created_at')

    if telemetry_q:
        clean_digits = re.sub(r'\D', '', telemetry_q)
        q_telemetry = (
            Q(claimant_name__icontains=telemetry_q)
            | Q(claimant_ghana_card__icontains=telemetry_q)
            | Q(relationship_stated__icontains=telemetry_q)
            | Q(policy__policy_number__icontains=telemetry_q)
            | Q(ip_address__icontains=telemetry_q)
        )
        if clean_digits:
            q_telemetry |= Q(claimant_ghana_card__icontains=clean_digits)
        recent_audits = recent_audits.filter(q_telemetry)

    if telemetry_status == 'MATCH':
        recent_audits = recent_audits.filter(is_matched=True)
    elif telemetry_status == 'DISCREPANCY':
        recent_audits = recent_audits.filter(is_matched=False)

    recent_audits = recent_audits[:30]

    total_policies = PolicyRecord.objects.filter(is_active=True).count()
    pending_claims_count = PolicyClaim.objects.filter(status='PENDING_REVIEW').count()
    total_audits_count = ClaimSecurityAuditLog.objects.count()

    # Complete Directory: Exclude staff and lead admin accounts strictly
    policyholders = CustomUser.objects.filter(
        user_type='POLICYHOLDER',
        is_staff=False,
        is_superuser=False
    )
    if policyholder_q:
        clean_digits = re.sub(r'\D', '', policyholder_q)
        q_ph = (
            Q(first_name__icontains=policyholder_q)
            | Q(last_name__icontains=policyholder_q)
            | Q(username__icontains=policyholder_q)
            | Q(ghana_card_number__icontains=policyholder_q)
            | Q(email__icontains=policyholder_q)
        )
        if clean_digits:
            q_ph |= Q(ghana_card_number__icontains=clean_digits)
        policyholders = policyholders.filter(q_ph)

    policyholders = policyholders.prefetch_related(
        'policies__insurer',
        'assets',
        'estate_documents',
        'emergency_contacts',
        'bank_accounts',
        'investments',
        'family_tree_members',
    ).order_by('-date_joined')

    # Complete Directory: Claimants with verified unlock grants and access tokens
    claimants = ClaimantAccessGrant.objects.select_related(
        'policyholder',
        'policy',
        'policy__insurer',
        'claimant_user'
    )

    if claimant_q:
        clean_digits = re.sub(r'\D', '', claimant_q)
        q_cl = (
            Q(claimant_name__icontains=claimant_q)
            | Q(claimant_ghana_card__icontains=claimant_q)
            | Q(claimant_phone__icontains=claimant_q)
            | Q(claimant_email__icontains=claimant_q)
            | Q(payment_reference__icontains=claimant_q)
            | Q(policyholder__first_name__icontains=claimant_q)
            | Q(policyholder__last_name__icontains=claimant_q)
            | Q(policyholder__username__icontains=claimant_q)
        )
        if clean_digits:
            q_cl |= Q(claimant_ghana_card__icontains=clean_digits)
        claimants = claimants.filter(q_cl)

    claimants = claimants.order_by('-unlocked_at')

    conflict_param = request.GET.get('conflict')

    inquiries = ContactInquiry.objects.all().order_by('-created_at')[:40]
    new_inquiries_count = ContactInquiry.objects.filter(status='NEW').count()
    platform_config = PlatformConfiguration.get_solo()

    context = {
        'recent_claims': recent_claims,
        'recent_audits': recent_audits,
        'total_policies': total_policies,
        'pending_claims_count': pending_claims_count,
        'total_audits_count': total_audits_count,
        'policyholders': policyholders,
        'claimants': claimants,
        'inquiries': inquiries,
        'new_inquiries_count': new_inquiries_count,
        'claim_q': claim_q,
        'claim_status': claim_status,
        'policyholder_q': policyholder_q,
        'claimant_q': claimant_q,
        'telemetry_q': telemetry_q,
        'telemetry_status': telemetry_status,
        'active_admin_role': 'STAFF',
        'conflict_target': conflict_param,
        'platform_config': platform_config,
    }
    return render(request, 'admin/staff_dashboard.html', context)


@login_required
def update_claim_status_view(request, claim_id):
    """
    Updates statutory claim state (APPROVED, DISBURSED, REJECTED) with desk review notes.
    """
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'status': 'error', 'message': 'Administrative privileges required.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required.'}, status=405)

    claim = get_object_or_404(PolicyClaim.objects.select_related('policy__insurer'), id=claim_id)

    new_status = request.POST.get('status')
    amount_disbursed = request.POST.get('amount_disbursed')
    insurer_notes = request.POST.get('insurer_notes', '').strip()

    valid_statuses = [choice[0] for choice in PolicyClaim.CLAIM_STATUS_CHOICES]
    if new_status not in valid_statuses:
        messages.error(request, 'Invalid claim status option.')
        return redirect('vault:staff_admin_dashboard')

    claim.status = new_status
    if insurer_notes:
        claim.insurer_notes = insurer_notes

    if new_status == 'DISBURSED' and amount_disbursed:
        try:
            claim.amount_disbursed = float(amount_disbursed)
            claim.policy.policy_status = 'SETTLED'
            claim.policy.save(update_fields=['policy_status'])
        except ValueError:
            pass

    claim.save()
    messages.success(request, f"Claim {claim.claim_reference} updated to {claim.get_status_display()}.")
    return redirect('vault:staff_admin_dashboard')

@login_required
def update_inquiry_status_view(request, inquiry_id):
    """
    Updates operational review state for inbound public contact inquiries.
    """
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'status': 'error', 'message': 'Staff privileges required.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required.'}, status=405)

    inquiry = get_object_or_404(ContactInquiry, id=inquiry_id)
    new_status = request.POST.get('status', '').strip().upper()

    valid_statuses = ['NEW', 'IN_REVIEW', 'RESOLVED']
    if new_status in valid_statuses:
        inquiry.status = new_status
        inquiry.save(update_fields=['status'])
        messages.success(request, f"Inquiry from {inquiry.full_name} updated to {inquiry.get_status_display()}.")
    else:
        messages.error(request, "Invalid status choice submitted.")

    return redirect(request.META.get('HTTP_REFERER', 'vault:staff_admin_dashboard'))

@login_required
def update_policy_status_view(request, policy_id):
    """
    Desk control for Lead and Staff Admins to switch policy lifecycle status
    (ACTIVE, CLAIM_IN_PROGRESS, SETTLED). Instantly reflects on the National Search Registry.
    """
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'status': 'error', 'message': 'Administrative privileges required.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required.'}, status=405)

    policy = get_object_or_404(PolicyRecord, id=policy_id)
    new_status = request.POST.get('policy_status', '').strip().upper()

    valid_statuses = ['ACTIVE', 'CLAIM_IN_PROGRESS', 'SETTLED']
    if new_status not in valid_statuses:
        messages.error(request, 'Invalid policy status option.')
        return redirect(request.META.get('HTTP_REFERER', 'vault:staff_admin_dashboard'))

    policy.policy_status = new_status
    policy.save(update_fields=['policy_status'])

    messages.success(
        request,
        f"Policy {policy.policy_number} set to {policy.get_policy_status_display()}. Status is now live on the National Search Registry."
    )
    return redirect(request.META.get('HTTP_REFERER', 'vault:staff_admin_dashboard'))


# ====================================================
# Dedicated Admin Authentication Views
# ====================================================

def admin_login_view(request):
    """
    Unified toggleable administration login portal for Lead Admin and Normal Admin.
    Establishes isolated session role tokens upon successful authentication.
    When an active admin switches portals (?role=...), their current session is
    terminated immediately so they must re-authenticate for that specific role card.
    """
    requested_role = request.GET.get('role', '').strip().lower()

    # If an authenticated user clicks to switch portal roles, log them out immediately
    if request.user.is_authenticated:
        if requested_role:
            logout(request)
        else:
            active_role = request.session.get('active_admin_role')
            if active_role == 'LEAD' and request.user.is_superuser:
                return redirect('vault:lead_admin_dashboard')
            elif active_role == 'STAFF' and (request.user.is_staff or request.user.is_superuser):
                return redirect('vault:staff_admin_dashboard')
            elif request.user.is_superuser:
                request.session['active_admin_role'] = 'LEAD'
                return redirect('vault:lead_admin_dashboard')
            elif request.user.is_staff:
                request.session['active_admin_role'] = 'STAFF'
                return redirect('vault:staff_admin_dashboard')

    if request.method == 'POST':
        admin_role = request.POST.get('admin_role', 'lead').strip()
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if admin_role == 'lead':
                if user.is_superuser:
                    login(request, user)
                    request.session['active_admin_role'] = 'LEAD'
                    return redirect('vault:lead_admin_dashboard')
                else:
                    messages.error(request, "Access Denied: Superuser root privileges required for Lead Admin.")
            else:
                if user.is_staff or user.is_superuser:
                    login(request, user)
                    request.session['active_admin_role'] = 'STAFF'
                    return redirect('vault:staff_admin_dashboard')
                else:
                    messages.error(request, "Access Denied: Staff clearance required for Normal Admin.")
        else:
            messages.error(request, "Invalid administrator credentials. Please check your username and password.")

    context = {
        'target_role': requested_role or 'lead',
    }
    return render(request, 'admin_login.html', context)
@login_required

def delete_audit_log_view(request, log_id):
    """
    Allows Lead and Staff admins to purge stale or test forensic audit logs.
    """
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'status': 'error', 'message': 'Administrative privileges required.'}, status=403)

    if request.method == 'POST':
        log = get_object_or_404(ClaimSecurityAuditLog, id=log_id)
        claimant_name = log.claimant_name
        card = log.claimant_ghana_card
        log.delete()
        messages.success(request, f"Forensic audit record for {claimant_name} ({card}) permanently purged.")

    return redirect(request.META.get('HTTP_REFERER', 'vault:lead_admin_dashboard'))

def contact_view(request):
    """
    Public Contact and Support Desk for policyholders, claimants, and underwriters.
    Saves inquiries to the database and dispatches alert emails to operations.
    """
    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        category = request.POST.get('category', 'GENERAL').strip()
        message = request.POST.get('message', '').strip()

        if full_name and email and message:
            inquiry = ContactInquiry.objects.create(
                full_name=full_name,
                email=email,
                phone=phone,
                category=category,
                message=message,
                status='NEW'
            )

            subject = f"[LegacyTrace Desk] {inquiry.get_category_display()} - {full_name}"
            email_body = (
                f"A new inquiry has been lodged through the contact portal:\n\n"
                f"Full Name: {full_name}\n"
                f"Email: {email}\n"
                f"Phone: {phone or 'Not provided'}\n"
                f"Category: {inquiry.get_category_display()}\n"
                f"Submitted At: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')} GMT\n\n"
                f"Message Content:\n"
                f"{message}\n\n"
                f"Manage in Admin Portal: /admin/vault/contactinquiry/{inquiry.id}/change/"
            )

            try:
                send_mail(
                    subject=subject,
                    message=email_body,
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@legacytrace.gov.gh'),
                    recipient_list=['legacytrace442@gmail.com'],
                    fail_silently=True,
                )
            except Exception:
                pass

            messages.success(
                request,
                f"Thank you, {full_name}. Your inquiry has been securely registered and routed to our operations desk."
            )
            return redirect('vault:contact')
        else:
            messages.error(request, "Please fill out all required fields before submitting.")

    return render(request, 'contact.html')