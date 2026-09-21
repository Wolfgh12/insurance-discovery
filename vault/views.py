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
from django.db import transaction
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

PAYSTACK_SECRET_KEY = getattr(settings, 'PAYSTACK_SECRET_KEY', None)


def get_client_ip(request):
    """Resolves origin IP, prioritizing REMOTE_ADDR unless in production behind a verified reverse proxy."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for and not settings.DEBUG:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip or '127.0.0.1'


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
        clean_card = query.replace('-', '').replace(' ', '').upper()

        card_variations = [query, clean_card]
        if clean_digits:
            card_variations.extend([
                clean_digits,
                f"GHA-{clean_digits}",
                f"GHA{clean_digits}",
            ])
            if len(clean_digits) >= 10:
                card_variations.extend([
                    f"GHA-{clean_digits[:9]}-{clean_digits[9:10]}",
                    f"{clean_digits[:9]}-{clean_digits[9:10]}",
                ])
            if len(clean_digits) >= 9:
                card_variations.append(clean_digits[:9])

        user_q = (
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(username__icontains=query)
        )
        for var in set(card_variations):
            if var:
                user_q |= Q(ghana_card_number__iexact=var)
                user_q |= Q(ghana_card_number__icontains=var)

        matched_users = list(CustomUser.objects.filter(user_q))

        policy_q = (
            Q(policyholder__in=matched_users)
            | Q(policy_number__icontains=query)
            | Q(policyholder__first_name__icontains=query)
            | Q(policyholder__last_name__icontains=query)
            | Q(policyholder__username__icontains=query)
        )
        for var in set(card_variations):
            if var:
                policy_q |= Q(policyholder__ghana_card_number__iexact=var)
                policy_q |= Q(policyholder__ghana_card_number__icontains=var)

        existing_policies = list(
            PolicyRecord.objects.filter(policy_q)
            .select_related('policyholder', 'insurer', 'policyholder__subscription')
            .prefetch_related('unlock_grants', 'claims')
        )

        results = existing_policies

    total_insurers = InsuranceCompany.objects.filter(is_verified=True).count()
    platform_config = PlatformConfiguration.get_solo()

    context = {
        'query': query,
        'results': results,
        'has_searched': has_searched,
        'total_insurers': total_insurers or 6,
        'unlock_fee': platform_config.unlock_fee,
        'unlock_fee_pesewas': platform_config.unlock_fee_pesewas,
        'platform_config': platform_config,
    }
    return render(request, 'home.html', context)

def pricing_view(request):
    """
    Public pricing page presenting quarterly and annual digital estate vault plans.
    """
    platform_config = PlatformConfiguration.get_solo()
    context = {
        'paystack_public_key': getattr(settings, 'PAYSTACK_PUBLIC_KEY', 'pk_test_f74c99ee13063ecc39fd9af4be16f23de21a11b3'),
        'platform_config': platform_config,
    }
    return render(request, 'pricing.html', context)


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

    if request.user.username.startswith('claimant_'):
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

        platform_config = PlatformConfiguration.get_solo()
        expected_pesewas = platform_config.annual_fee_pesewas if billing_cycle == 'ANNUALLY' else platform_config.registration_fee_pesewas
        paid_pesewas = data_payload.get('amount', 0)

        if resp_data.get('status') and data_payload.get('status') == 'success' and int(paid_pesewas) >= expected_pesewas:
            payment_verified = True
            amount_paid = float(paid_pesewas) / 100.0
            customer_code = data_payload.get('customer', {}).get('customer_code', '')
            auth_code = data_payload.get('authorization', {}).get('authorization_code', '')
            plan_obj = data_payload.get('plan_object') or {}
            subscriptions_list = plan_obj.get('subscriptions', [])
            if subscriptions_list:
                subscription_code = subscriptions_list[0].get('subscription_code', '')
    except Exception:
        # Strict Production Guard: Mock prefixes are ONLY permitted in local DEBUG environments
        if settings.DEBUG and reference.startswith('SUB-'):
            payment_verified = True
            amount_paid = 1200.00 if billing_cycle == 'ANNUALLY' else 450.00
        else:
            payment_verified = False

    if not payment_verified:
        return JsonResponse({'status': 'error', 'message': 'Payment verification failed.'}, status=400)

    start_date = timezone.now()
    if billing_cycle == 'QUARTERLY':
        end_date = start_date + timedelta(days=92)
    else:
        end_date = start_date + timedelta(days=365)

    with transaction.atomic():
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
    1. Enforces 15-minute IP lockout on 5 consecutive false/unmatched attempts.
    2. Captures front, left, and right profile snapshots.
    3. Returns opaque security response on mismatch without exposing network telemetry.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST method required.'}, status=405)

    client_ip = get_client_ip(request)
    claimant_throttle_key = f"throttle_claimant_audit_{client_ip}"
    failed_attempts = cache.get(claimant_throttle_key, 0)

    # Rate Limiting: Lock out IP after 5 failed identity attempts to halt automated brute-force attacks
    if failed_attempts >= 5:
        return JsonResponse({
            'status': 'error',
            'message': 'Too many failed identity verification attempts from this network. Access locked for 15 minutes.'
        }, status=429)

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

    # Sovereign Ghana Card Lock: Remains globally enforced across all citizens and grants
    clean_card = claimant_ghana_card.replace('-', '').replace(' ', '').upper()
    if (
        CustomUser.objects.filter(
            Q(ghana_card_number__iexact=claimant_ghana_card) | Q(ghana_card_number__iexact=clean_card)
        ).exists()
        or ClaimantAccessGrant.objects.filter(
            Q(claimant_ghana_card__iexact=claimant_ghana_card) | Q(claimant_ghana_card__iexact=clean_card)
        ).exists()
    ):
        return JsonResponse({
            'status': 'collision_error',
            'field': 'ghana_card',
            'message': 'This Ghana Card ID is already registered in the system. Please verify your ID details.'
        })

    # Claimed & Settled Exemption: Allows family members to reuse phone and email details from claimed estates
    claimed_policyholder_q = (
        Q(policies__policy_status__in=['CLAIM_IN_PROGRESS', 'SETTLED'])
        | Q(policies__unlock_grants__is_active=True)
        | Q(policies__claims__isnull=False)
    )

    clean_phone_digits = re.sub(r'\D', '', claimant_phone)[-9:]
    if clean_phone_digits and (
        CustomUser.objects.filter(phone_number__endswith=clean_phone_digits).exclude(claimed_policyholder_q).exists()
        or ClaimantAccessGrant.objects.filter(claimant_phone__endswith=clean_phone_digits).exclude(policy__policy_status='SETTLED').exists()
    ):
        return JsonResponse({
            'status': 'collision_error',
            'field': 'phone',
            'message': 'This phone number is already registered in the system. Please provide an unregistered contact number.'
        })

    if claimant_email and (
        CustomUser.objects.filter(email__iexact=claimant_email).exclude(claimed_policyholder_q).exists()
        or ClaimantAccessGrant.objects.filter(claimant_email__iexact=claimant_email).exclude(policy__policy_status='SETTLED').exists()
    ):
        return JsonResponse({
            'status': 'collision_error',
            'field': 'email',
            'message': 'This email address is already registered in the system. Please use a different email address.'
        })

    client_ip = get_client_ip(request) or '127.0.0.1'
    user_agent = request.META.get('HTTP_USER_AGENT', 'Unknown')
    clean_card_digits = re.sub(r'\D', '', claimant_ghana_card)

    front_file = decode_base64_image(biometric_front_b64, file_prefix=f"{clean_card_digits}_front")
    left_file = decode_base64_image(biometric_left_b64, file_prefix=f"{clean_card_digits}_left")
    right_file = decode_base64_image(biometric_right_b64, file_prefix=f"{clean_card_digits}_right")

    clean_claimant_phone = re.sub(r'\D', '', claimant_phone)[-9:]
    registered_contacts = EmergencyContact.objects.filter(user=policyholder)
    is_matched = False

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

        claimant_tokens = {t for t in claimant_name.lower().split() if len(t) >= 3}
        contact_tokens = {t for t in contact.full_name.lower().split() if len(t) >= 3}
        name_match = bool(claimant_tokens & contact_tokens) or (claimant_name.lower() in contact.full_name.lower())

        relation_match = relations_compatible(relationship, contact.relationship)

        if phone_match and name_match and relation_match:
            is_matched = True
            break

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

    # Increment throttle count: 15-minute (900s) timeout window
    new_fails = failed_attempts + 1
    cache.set(claimant_throttle_key, new_fails, timeout=900)

    return JsonResponse({
        'status': 'mismatch_flagged',
        'is_matched': False,
        'audit_id': audit_log.id,
        'message': 'Identity verification failed. The provided details do not match the registered next-of-kin records. All submitted details and facial verifications have been permanently recorded in the security audit vault.',
    })


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
    claimant_email = data.get('email', 'claimant@mysikavault.com')
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

    with transaction.atomic():
        # Enforce ACID row-level mutual exclusion lock (SELECT ... FOR UPDATE)
        policy = get_object_or_404(
            PolicyRecord.objects.select_for_update().select_related('policyholder', 'insurer'), 
            id=record_id
        )

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

    payment_verified = False
    platform_config = PlatformConfiguration.get_solo()

    try:
        resp = requests.get(paystack_url, headers=headers, timeout=10)
        resp_data = resp.json()
        data_payload = resp_data.get('data', {})
        if resp_data.get('status') and data_payload.get('status') == 'success':
            amount_paid_pesewas = data_payload.get('amount')
            if amount_paid_pesewas and int(amount_paid_pesewas) >= platform_config.unlock_fee_pesewas:
                payment_verified = True
    except Exception:
        # Strict Production Guard: Mock prefixes are ONLY permitted in local DEBUG environments
        if settings.DEBUG and reference.startswith('LT-'):
            payment_verified = True
        else:
            payment_verified = False

    if not payment_verified:
        return JsonResponse({'status': 'error', 'message': 'Payment verification failed.'}, status=400)

    with transaction.atomic():
        policy = get_object_or_404(
            PolicyRecord.objects.select_for_update().select_related('policyholder', 'insurer'), 
            id=record_id
        )

        # TOCTOU Concurrency Guard: Re-verify lock state after external Paystack HTTP roundtrip
        if policy.is_claim_locked:
            return JsonResponse({
                'status': 'error',
                'message': 'This policy was already locked by another completed transaction.'
            }, status=400)

        policyholder = policy.policyholder
        access_token = secrets.token_urlsafe(24)

        # Collision-Proof Unique Username Generation
        while True:
            claimant_username = f"claimant_{secrets.token_hex(6)}"
            if not CustomUser.objects.filter(username=claimant_username).exists():
                break

        temp_password = f"LT-{secrets.token_hex(4).upper()}"
        name_parts = claimant_name.split(' ', 1) if claimant_name else ['Verified', 'Claimant']
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ''

        claimant_user = CustomUser.objects.create(
            username=claimant_username,
            email=None,
            first_name=first_name,
            last_name=last_name,
            phone_number=claimant_phone,
            ghana_card_number=None,
            permanent_address=permanent_address,
            user_type='POLICYHOLDER',
        )
        claimant_user.set_password(temp_password)
        claimant_user.save()

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
            'temporary_password': temp_password,
            'is_existing_account': False,
            'claimant_email': claimant_email,
        },
        'unlocked_data': {
            'insurer_name': policy.insurer.name,
            'insurer_contact': policy.insurer.contact_email,
            'claims_hotline': policy.insurer.claims_hotline,
            'policy_number': policy.policy_number,
            'policy_type': policy.get_policy_type_display(),
            'policy_status': policy.get_policy_status_display(),
            'sum_assured': float(policy.sum_assured or 0.0),
            'total_premiums_paid': float(policy.total_premiums_paid or 0.0),
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

    # Verify grant remains active
    if grant_record and not grant_record.is_active:
        messages.error(
            request, 
            "This estate docket has been formally closed or archived. Please contact support if you need assistance."
        )
        return redirect('vault:claimant_login')

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
    """
    Citizen registration endpoint:
    Creates account with zero upfront payment gate and redirects to login.
    """
    if request.user.is_authenticated:
        if (
            request.user.is_staff
            or request.user.is_superuser
            or request.user.username.startswith('claimant_')
        ):
            logout(request)
        else:
            return redirect('vault:dashboard')

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.user_type = 'POLICYHOLDER'
            user.has_paid_registration_fee = False
            user.save()
            form.save_m2m()

            method = form.cleaned_data.get('verification_method')

            if method == 'EMAIL':
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                activation_url = request.build_absolute_uri(
                    reverse('vault:activate_account', kwargs={'uidb64': uid, 'token': token})
                )

                email_subject = "mySikaVault | Confirm Your Registration"
                email_message = (
                    f"Hello {user.first_name or user.username},\n\n"
                    f"Thank you for registering your digital estate vault on mySikaVault.\n\n"
                    f"Please click the secure statutory link below to activate your account and configure your identity recovery keys:\n"
                    f"{activation_url}\n\n"
                    f"This link is valid for 24 hours. If you did not initiate this registration, please disregard this email.\n\n"
                    f"mySikaVault National Registry Desk"
                )

                try:
                    send_mail(
                        subject=email_subject,
                        message=email_message,
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@mysikavault.com'),
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                    messages.success(
                        request,
                        f"Registration successful! An activation link has been sent to {user.email}. Please verify your email to log in."
                    )
                except Exception:
                    messages.warning(
                        request,
                        "Vault created, but email dispatch timed out. Please try signing in."
                    )
                return redirect('vault:login')
            else:
                messages.success(
                    request,
                    f"Vault account created successfully, {user.first_name or user.username}! Please sign in to activate your vault."
                )
                return redirect('vault:login')
    else:
        form = SignUpForm()

    platform_config = PlatformConfiguration.get_solo()
    context = {
        'form': form,
        'platform_config': platform_config,
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

    # If the user already has recovery answers configured, forward directly to dashboard
    if user.has_security_questions_configured and not request.GET.get('force'):
        return redirect('vault:dashboard')

    if request.method == 'POST':
        form = SecurityQuestionsSetupForm(request.POST)
        if form.is_valid():
            form.save(user=user)
            messages.success(
                request,
                "Security recovery keys configured successfully!"
            )
            # Enforce statutory GHS 10 fee settlement immediately after security setup
            if not user.has_paid_registration_fee and not (user.is_staff or user.is_superuser):
                messages.info(request, "Please settle the statutory one-time onboarding fee (GHS 10.00) to open your vault.")
                return redirect('vault:login')

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
    client_ip = get_client_ip(request)
    ip_throttle_key = f"throttle_ip_{client_ip}"

    def prompt_single_saved_question(target_user):
        """Fetches 1 random question exclusively from the questions answered during registration."""
        saved_answers = list(target_user.security_answers.select_related('question').filter(question__is_active=True))

        if saved_answers:
            chosen = random.choice(saved_answers)
            request.session['login_security_challenge'] = {
                'user_id': target_user.id,
                'question_key': str(chosen.question_id),
                'question_prompt': chosen.question.question_text,
                'next_url': next_url,
            }
            return render(request, 'registration/login.html', {
                'challenge_required': True,
                'challenge_question': chosen.question.question_text,
                'next': next_url,
            })

        legacy_questions = []
        if target_user.security_birth_city:
            legacy_questions.append(('birth_city', 'Where were you born?'))
        if target_user.security_mother_maiden_name:
            legacy_questions.append(('mother_maiden_name', "What is your mother's maiden name?"))
        if target_user.security_high_school_crush:
            legacy_questions.append(('high_school_crush', 'Who was your first high school crush?'))

        if legacy_questions:
            chosen_key, chosen_prompt = random.choice(legacy_questions)
            request.session['login_security_challenge'] = {
                'user_id': target_user.id,
                'question_key': chosen_key,
                'question_prompt': chosen_prompt,
                'next_url': next_url,
            }
            return render(request, 'registration/login.html', {
                'challenge_required': True,
                'challenge_question': chosen_prompt,
                'next': next_url,
            })

        cache.delete(ip_throttle_key)
        clean_user_id = re.sub(r'[\s\-]', '', target_user.username).lower()
        cache.delete(f"throttle_acc_{clean_user_id}")
        login(request, target_user)
        messages.success(request, f"Welcome back, {target_user.first_name or target_user.username}!")
        return redirect(next_url)

    if request.method == 'GET':
        request.session.pop('login_security_challenge', None)
        request.session.pop('login_pending_user_id', None)
        return render(request, 'registration/login.html', {'next': next_url})

    action = request.POST.get('action')

    # Stage 3: Validate the single question answered and log in
    if action == 'verify_security_challenge':
        challenge_data = request.session.get('login_security_challenge')
        if not challenge_data:
            messages.error(request, "Session expired or invalid. Please sign in again.")
            return redirect('vault:login')

        user = get_object_or_404(CustomUser, id=challenge_data.get('user_id'))
        question_key = challenge_data.get('question_key')
        question_prompt = challenge_data.get('question_prompt', 'Security Question')
        next_destination = challenge_data.get('next_url', next_url)
        answer = request.POST.get('security_answer', '').strip()

        if user.verify_security_answer(question_key, answer):
            cache.delete(ip_throttle_key)
            clean_user_id = re.sub(r'[\s\-]', '', user.username).lower()
            cache.delete(f"throttle_acc_{clean_user_id}")
            request.session.pop('login_security_challenge', None)
            request.session.pop('login_pending_user_id', None)
            login(request, user)
            messages.success(request, f"Identity confirmed. Welcome back, {user.first_name or user.username}!")
            return redirect(next_destination)
        else:
            failed_attempts = cache.get(ip_throttle_key, 0) + 1
            cache.set(ip_throttle_key, failed_attempts, timeout=900)
            messages.error(request, "Incorrect security answer. Access denied.")
            return render(request, 'registration/login.html', {
                'challenge_required': True,
                'challenge_question': question_prompt,
                'next': next_destination,
            })

    # Stage 2: Settle GHS 10.00 Fee -> Immediately serve 1 random saved question
    if action == 'confirm_registration_fee':
        user_id = request.session.get('login_pending_user_id')
        if not user_id:
            messages.error(request, "Session expired. Please enter your credentials again.")
            return redirect('vault:login')

        user = get_object_or_404(CustomUser, id=user_id)
        reference = request.POST.get('reference', '').strip()

        if not reference:
            messages.error(request, "Payment reference required.")
            return redirect('vault:login')

        paystack_url = f"https://api.paystack.co/transaction/verify/{reference}"
        headers = {
            "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }

        verified = False
        platform_config = PlatformConfiguration.get_solo()
        try:
            resp = requests.get(paystack_url, headers=headers, timeout=10)
            resp_data = resp.json()
            data_payload = resp_data.get('data', {})
            paid_pesewas = data_payload.get('amount', 0)
            if resp_data.get('status') and data_payload.get('status') == 'success' and int(paid_pesewas) >= platform_config.registration_fee_pesewas:
                verified = True
        except Exception:
            # Strict Production Guard: Mock prefixes are ONLY permitted in local DEBUG environments
            if settings.DEBUG and reference.startswith('REG-'):
                verified = True
            else:
                verified = False

        if not verified:
            messages.error(request, "Statutory registration fee could not be verified. Please try again.")
            platform_config = PlatformConfiguration.get_solo()
            return render(request, 'registration/login.html', {
                'fee_required': True,
                'pending_user': user,
                'next': next_url,
                'paystack_public_key': getattr(settings, 'PAYSTACK_PUBLIC_KEY', 'pk_test_f74c99ee13063ecc39fd9af4be16f23de21a11b3'),
                'platform_config': platform_config,
            })

        user.has_paid_registration_fee = True
        user.registration_payment_reference = reference
        user.save(update_fields=['has_paid_registration_fee', 'registration_payment_reference'])
        messages.success(request, "Statutory onboarding fee confirmed! Answer your security question to open your vault.")

        return prompt_single_saved_question(user)

    # Stage 1: Dual-Key Brute-Force Check (IP + Target Account)
    username_or_card = request.POST.get('username', '').strip()
    password = request.POST.get('password', '').strip()
    clean_card = username_or_card.replace('-', '').replace(' ', '')
    clean_identifier = re.sub(r'[\s\-]', '', username_or_card).lower()
    account_throttle_key = f"throttle_acc_{clean_identifier}" if clean_identifier else None

    ip_fails = cache.get(ip_throttle_key, 0)
    acc_fails = cache.get(account_throttle_key, 0) if account_throttle_key else 0

    if ip_fails >= 5:
        messages.error(
            request, 
            "Too many failed login attempts recorded from this network. Access locked for 15 minutes."
        )
        return redirect('vault:login')

    if acc_fails >= 5:
        messages.error(
            request, 
            "This account is temporarily locked due to excessive failed attempts. Access locked for 15 minutes."
        )
        return redirect('vault:login')

    matched_user = CustomUser.objects.filter(
        Q(username__iexact=username_or_card)
        | Q(email__iexact=username_or_card)
        | Q(ghana_card_number__iexact=username_or_card)
        | Q(ghana_card_number__iexact=clean_card)
    ).first()

    login_fail_url = reverse('vault:login')
    if next_url and next_url != '/dashboard/':
        login_fail_url += f'?next={next_url}'

    if matched_user and not matched_user.is_active:
        messages.error(
            request,
            "This account is pending email activation. Please check your inbox or spam folder for your confirmation link."
        )
        return redirect(login_fail_url)

    target_username = matched_user.username if matched_user else username_or_card
    user = authenticate(request, username=target_username, password=password)

    if user is not None:
        cache.delete(ip_throttle_key)
        if account_throttle_key:
            cache.delete(account_throttle_key)

        if user.is_superuser:
            return redirect('vault:admin_login')
        elif user.is_staff or user.user_type in ['STAFF', 'INSURER_ADMIN']:
            return redirect('vault:admin_login')

        # If GHS 10 fee is unpaid, present fee card first
        if not user.has_paid_registration_fee:
            request.session['login_pending_user_id'] = user.id
            platform_config = PlatformConfiguration.get_solo()
            return render(request, 'registration/login.html', {
                'fee_required': True,
                'pending_user': user,
                'next': next_url,
                'paystack_public_key': getattr(settings, 'PAYSTACK_PUBLIC_KEY', 'pk_test_f74c99ee13063ecc39fd9af4be16f23de21a11b3'),
                'platform_config': platform_config,
            })

        # Fee already paid -> Present 1 random saved question
        return prompt_single_saved_question(user)

    new_ip_fails = ip_fails + 1
    cache.set(ip_throttle_key, new_ip_fails, timeout=900)
    if account_throttle_key:
        cache.set(account_throttle_key, acc_fails + 1, timeout=900)

    remaining = max(0, 5 - new_ip_fails)
    messages.error(
        request, 
        f"Invalid username or password. {remaining} attempt{'s' if remaining != 1 else ''} remaining before temporary lockout."
    )
    return redirect(login_fail_url)


def forgot_password_view(request):
    """
    Dual-Path Password Recovery Flow:
    1. Resolves citizen account via Username, Email, or Ghana Card ID (via CustomUser.find_by_identifier).
    2. Offers two distinct pathways:
       - Route A (Email Reset Link): Dispatches a one-time cryptographic reset token to the user's email with zero questions asked.
       - Route B (Statutory Security Questions): Prompts the user to answer all configured security recovery keys on-screen.
    """
    if request.user.is_authenticated:
        return redirect('vault:dashboard')

    if request.method == 'GET':
        if request.GET.get('reset'):
            request.session.pop('pwd_recovery_user_id', None)
            request.session.pop('pwd_reset_questions', None)
            request.session.pop('pwd_reset_attempts', None)
            return redirect('vault:forgot_password')

        user_id = request.session.get('pwd_recovery_user_id')
        if user_id:
            user = CustomUser.objects.filter(id=user_id, is_active=True).first()
            if user:
                questions = request.session.get('pwd_reset_questions')
                if questions:
                    return render(request, 'registration/forgot_password.html', {
                        'stage': 'questions',
                        'questions': questions,
                        'attempts': request.session.get('pwd_reset_attempts', 0),
                        'target_user': user,
                    })

                masked_email = None
                if user.email:
                    parts = user.email.split('@')
                    user_part = parts[0]
                    domain_part = parts[1] if len(parts) > 1 else ''
                    masked_email = f"{user_part[:2]}***@{domain_part}"

                return render(request, 'registration/forgot_password.html', {
                    'stage': 'select_path',
                    'target_user': user,
                    'masked_email': masked_email,
                    'has_questions': bool(user.get_security_questions()),
                })

        return render(request, 'registration/forgot_password.html', {'stage': 'lookup'})

    action = request.POST.get('action')

    # Step 1: Identifier Resolution (Username, Email, or Ghana Card ID)
    if action == 'lookup_citizen':
        identifier = request.POST.get('identifier', '').strip()
        user = CustomUser.find_by_identifier(identifier)

        if not user or not user.is_active:
            messages.error(request, "No registered citizen vault matches that identifier. Check for typos or re-enter your registered details.")
            return render(request, 'registration/forgot_password.html', {'stage': 'lookup', 'identifier': identifier})

        if user.is_superuser or user.is_staff or getattr(user, 'user_type', None) in ['STAFF', 'INSURER_ADMIN']:
            messages.error(request, "Administrative accounts cannot use citizen recovery. Please contact registry operations.")
            return redirect('vault:admin_login')

        request.session['pwd_recovery_user_id'] = user.id
        request.session.pop('pwd_reset_questions', None)
        request.session.pop('pwd_reset_attempts', None)

        masked_email = None
        if user.email:
            parts = user.email.split('@')
            user_part = parts[0]
            domain_part = parts[1] if len(parts) > 1 else ''
            masked_email = f"{user_part[:2]}***@{domain_part}"

        return render(request, 'registration/forgot_password.html', {
            'stage': 'select_path',
            'target_user': user,
            'masked_email': masked_email,
            'has_questions': bool(user.get_security_questions()),
        })

    # Route A: Send Direct Email Reset Link (Zero Questions Asked)
    elif action == 'send_email_link':
        user_id = request.session.get('pwd_recovery_user_id')
        user = get_object_or_404(CustomUser, id=user_id) if user_id else None

        if not user or not user.email:
            messages.error(request, "No email address on file for this vault. Please use the Statutory Questions path.")
            return redirect('vault:forgot_password')

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        reset_url = request.build_absolute_uri(
            reverse('vault:reset_password_confirm', kwargs={'uidb64': uid, 'token': token})
        )

        email_subject = "mySikaVault | Password Reset Confirmation"
        email_message = (
            f"Hello {user.first_name or user.username},\n\n"
            f"A password reset request was initiated for your mySikaVault digital vault.\n\n"
            f"Click the link below to set your new password:\n"
            f"{reset_url}\n\n"
            f"This link is valid for 24 hours. If you did not request a password reset, you can safely ignore this email.\n\n"
            f"mySikaVault National Registry Desk"
        )

        try:
            send_mail(
                subject=email_subject,
                message=email_message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@mysikavault.com'),
                recipient_list=[user.email],
                fail_silently=False,
            )
            messages.success(request, f"A secure reset link has been dispatched to {user.email}.")
        except Exception:
            messages.warning(request, "Reset link prepared, but delivery timed out. Please check your email inbox shortly.")

        request.session.pop('pwd_recovery_user_id', None)
        return render(request, 'registration/forgot_password.html', {
            'stage': 'email_sent',
            'user_email': user.email,
        })

    # Route B: Load Statutory Security Questions
    elif action == 'start_security_questions':
        user_id = request.session.get('pwd_recovery_user_id')
        user = get_object_or_404(CustomUser, id=user_id) if user_id else None

        if not user:
            messages.error(request, "Session expired. Please enter your account identifier again.")
            return redirect('vault:forgot_password')

        questions = user.get_security_questions()
        if not questions:
            messages.error(request, "No statutory questions are configured on this account. Please use the email reset option.")
            return redirect('vault:forgot_password')

        request.session['pwd_reset_questions'] = questions
        request.session['pwd_reset_attempts'] = 0

        return render(request, 'registration/forgot_password.html', {
            'stage': 'questions',
            'questions': questions,
            'attempts': 0,
            'target_user': user,
        })

    # Route B Verification: Evaluate All Security Answers Concurrently
    elif action == 'verify_all_security_answers':
        user_id = request.session.get('pwd_recovery_user_id')
        questions = request.session.get('pwd_reset_questions', [])
        attempts = request.session.get('pwd_reset_attempts', 0)

        if not user_id or not questions:
            messages.error(request, "Session expired. Please enter your account identifier to begin.")
            return redirect('vault:forgot_password')

        user = get_object_or_404(CustomUser, id=user_id)

        all_passed = True
        for q in questions:
            user_input = request.POST.get(f"answer_{q['id']}", '').strip()
            if not user.verify_security_answer(q['id'], user_input):
                all_passed = False
                break

        if all_passed:
            request.session.pop('pwd_recovery_user_id', None)
            request.session.pop('pwd_reset_questions', None)
            request.session.pop('pwd_reset_attempts', None)
            request.session['can_reset_password_user_id'] = user.id
            messages.success(request, "Statutory questions verified! Please enter your new password.")
            return redirect('vault:reset_password_direct')

        attempts += 1
        request.session['pwd_reset_attempts'] = attempts
        request.session.modified = True

        if attempts >= 3:
            # Automatic fallback: dispatch reset email on 3rd failure
            if user.email:
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                reset_url = request.build_absolute_uri(
                    reverse('vault:reset_password_confirm', kwargs={'uidb64': uid, 'token': token})
                )
                email_subject = "mySikaVault | Password Reset (Question Attempts Exceeded)"
                email_message = (
                    f"Hello {user.first_name or user.username},\n\n"
                    f"Three consecutive incorrect security answer attempts (3/3) were recorded for your vault.\n\n"
                    f"To restore your account securely, click the link below:\n"
                    f"{reset_url}\n\n"
                    f"mySikaVault National Registry Desk"
                )
                try:
                    send_mail(
                        subject=email_subject,
                        message=email_message,
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@mysikavault.com'),
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                except Exception:
                    pass

            request.session.pop('pwd_recovery_user_id', None)
            request.session.pop('pwd_reset_questions', None)
            request.session.pop('pwd_reset_attempts', None)

            return render(request, 'registration/forgot_password.html', {
                'stage': 'email_sent',
                'user_email': user.email,
                'max_attempts_exceeded': True,
            })

        remaining = 3 - attempts
        messages.error(
            request,
            f"One or more security answers are incorrect. Attempt {attempts} of 3 ({remaining} attempt{'s' if remaining != 1 else ''} remaining)."
        )
        return render(request, 'registration/forgot_password.html', {
            'stage': 'questions',
            'questions': questions,
            'attempts': attempts,
            'target_user': user,
        })

    return redirect('vault:forgot_password')


def reset_password_direct_view(request):
    """
    Direct password reset screen unlocked immediately after passing all security questions.
    """
    user_id = request.session.get('can_reset_password_user_id')
    if not user_id:
        messages.error(request, "Unauthorized password reset session. Please verify your identity first.")
        return redirect('vault:login')

    user = get_object_or_404(CustomUser, id=user_id)

    if request.method == 'POST':
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        if len(new_password) < 6:
            messages.error(request, "Password must be at least 6 characters long.")
        elif new_password != confirm_password:
            messages.error(request, "Passwords do not match. Please re-enter.")
        else:
            user.set_password(new_password)
            user.save()
            request.session.pop('can_reset_password_user_id', None)
            messages.success(request, "Password updated successfully! Please sign in with your new password.")
            return redirect('vault:login')

    return render(request, 'registration/reset_password.html', {'user_obj': user, 'is_direct': True})


def reset_password_confirm_view(request, uidb64, token):
    """
    Password reset screen reached via the automated fallback email link after 3 failed attempts.
    """
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = CustomUser.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        messages.error(request, "The password reset link is invalid or has expired. Please request a new one.")
        return redirect('vault:login')

    if request.method == 'POST':
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        if len(new_password) < 6:
            messages.error(request, "Password must be at least 6 characters long.")
        elif new_password != confirm_password:
            messages.error(request, "Passwords do not match. Please re-enter.")
        else:
            user.set_password(new_password)
            user.save()
            messages.success(request, "Password updated successfully! Please sign in with your new password.")
            return redirect('vault:login')

    return render(request, 'registration/reset_password.html', {
        'user_obj': user,
        'uidb64': uidb64,
        'token': token,
        'is_direct': False,
    })


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
    platform_config = PlatformConfiguration.get_solo()
    try:
        resp = requests.get(paystack_url, headers=headers, timeout=10)
        resp_data = resp.json()
        data_payload = resp_data.get('data', {})
        paid_pesewas = data_payload.get('amount', 0)
        if resp_data.get('status') and data_payload.get('status') == 'success' and int(paid_pesewas) >= platform_config.registration_fee_pesewas:
            verified = True
    except Exception:
        # Strict Production Guard: Mock prefixes are ONLY permitted in local DEBUG environments
        if settings.DEBUG and reference.startswith('REG-'):
            verified = True
        else:
            verified = False
    if not verified:
        return JsonResponse({'status': 'error', 'message': 'Payment verification failed.'}, status=400)

    with transaction.atomic():
        request.user.has_paid_registration_fee = True
        request.user.registration_payment_reference = reference
        request.user.save(update_fields=['has_paid_registration_fee', 'registration_payment_reference'])

    messages.success(request, "Statutory registration fee of GHS 10.00 settled! Your citizen account is now verified.")
    return JsonResponse({'status': 'success', 'message': 'Registration fee verified successfully.'})


@login_required
def dashboard_view(request):
    user = request.user

    if user.is_superuser:
        messages.warning(request, "Lead Admins cannot hold personal estate vaults in this session. Please register or log in with a citizen account.")
        return redirect('vault:lead_admin_dashboard')
    elif user.is_staff or getattr(user, 'user_type', None) in ['STAFF', 'INSURER_ADMIN']:
        messages.warning(request, "Operations staff cannot hold personal estate vaults in this session. Please register or log in with a citizen account.")
        return redirect('vault:staff_admin_dashboard')

    if user.username.startswith('claimant_'):
        return redirect('vault:claimant_dashboard')

    if not user.has_security_questions_configured and not (user.is_staff or user.is_superuser):
        messages.warning(
            request,
            "Security configuration incomplete: Please configure your security recovery keys to enter your vault."
        )
        return redirect('vault:security_questions_setup')

    if not user.has_paid_registration_fee and not (user.is_staff or user.is_superuser):
        messages.info(request, "Please settle the statutory one-time onboarding fee (GHS 10.00) to open your vault.")
        return redirect('vault:login')

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

    platform_config = PlatformConfiguration.get_solo()

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
            else:
                for errors in contact_form.errors.values():
                    for err in errors:
                        messages.error(request, err)
                return redirect('vault:dashboard')

        elif action == 'edit_emergency_contact':
            contact_id = request.POST.get('contact_id')
            contact = get_object_or_404(EmergencyContact, id=contact_id, user=user)
            edit_form = EmergencyContactForm(request.POST, instance=contact)
            if edit_form.is_valid():
                edit_form.save()
                messages.success(request, f'Emergency contact "{contact.full_name}" updated successfully.')
            else:
                for errors in edit_form.errors.values():
                    for err in errors:
                        messages.error(request, err)
            return redirect('vault:dashboard')

        elif action == 'delete_emergency_contact':
            contact_id = request.POST.get('contact_id')
            contact = get_object_or_404(EmergencyContact, id=contact_id, user=user)
            contact_name = contact.full_name
            contact.delete()
            messages.success(request, f'Emergency contact "{contact_name}" removed from your vault.')
            return redirect('vault:dashboard')

        elif action in ['add_policy', 'edit_policy']:
            if not platform_config.module_policies_enabled:
                messages.warning(request, "The Insurance Policies module is currently in Coming Soon mode.")
                return redirect('vault:dashboard')

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
            else:
                for errors in policy_form.errors.values():
                    for err in errors:
                        messages.error(request, err)
                return redirect('vault:dashboard')

        elif action == 'edit_policy':
            policy_id = request.POST.get('policy_id')
            policy = get_object_or_404(PolicyRecord, id=policy_id, policyholder=user)
            edit_policy_form = PolicyRecordForm(request.POST, instance=policy)
            if edit_policy_form.is_valid():
                edit_policy_form.save()
                messages.success(request, f'Policy "{policy.policy_number}" updated successfully.')
            else:
                for errors in edit_policy_form.errors.values():
                    for err in errors:
                        messages.error(request, err)
            return redirect('vault:dashboard')

        elif action == 'delete_policy':
            policy_id = request.POST.get('policy_id')
            policy = get_object_or_404(PolicyRecord, id=policy_id, policyholder=user)
            num = policy.policy_number
            policy.delete()
            messages.success(request, f'Policy "{num}" removed from your vault.')
            return redirect('vault:dashboard')

        elif action == 'add_asset':
            if not platform_config.module_assets_enabled:
                messages.warning(request, "Property & Assets module is currently in Coming Soon mode.")
                return redirect('vault:dashboard')

            asset_form = AssetRecordForm(request.POST, request.FILES)
            if asset_form.is_valid():
                asset = asset_form.save(commit=False)
                asset.user = user
                asset.save()
                messages.success(request, 'Property/Asset record secured.')
                return redirect('vault:dashboard')

        elif action == 'add_document':
            if not platform_config.module_wills_enabled:
                messages.warning(request, "Digital Wills & Deeds module is currently in Coming Soon mode.")
                return redirect('vault:dashboard')

            doc_form = EstateDocumentForm(request.POST, request.FILES)
            if doc_form.is_valid():
                doc = doc_form.save(commit=False)
                doc.user = user
                doc.save()
                messages.success(request, 'Digital Will / Legal Document deposited.')
                return redirect('vault:dashboard')

        elif action == 'add_bank_account':
            if not platform_config.module_banks_enabled:
                messages.warning(request, "Bank Accounts module is currently in Coming Soon mode.")
                return redirect('vault:dashboard')
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
            if not platform_config.module_investments_enabled:
                messages.warning(request, "Investments & T-Bills module is currently in Coming Soon mode.")
                return redirect('vault:dashboard')

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
                        pass

                sub.status = 'CANCELLED'
                sub.auto_renew = False
                sub.save(update_fields=['status', 'auto_renew'])
                messages.success(
                    request,
                    'Your active subscription has been cancelled. You can now select and activate a new plan on the pricing page.'
                )
            return redirect('vault:dashboard')

        elif action == 'add_memory':
            if not platform_config.module_memories_enabled:
                messages.warning(request, "Memory Lane & Keepsakes module is currently in Coming Soon mode.")
                return redirect('vault:dashboard')

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
            if not platform_config.module_memories_enabled:
                messages.warning(request, "Milestone suggestions are currently unavailable.")
                return redirect('vault:dashboard')

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
            if not platform_config.module_family_tree_enabled:
                messages.warning(request, "Family Tree module is currently in Coming Soon mode.")
                return redirect('vault:dashboard')

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

    cutoff_24h = timezone.now() - timedelta(hours=24)
    my_suggestions = user.suggested_milestones.filter(
        Q(status='PENDING_REVIEW') |
        Q(status='APPROVED') |
        Q(status='REJECTED', updated_at__gte=cutoff_24h)
    ).order_by('-created_at')

    if not MilestonePrompt.objects.exists():
        MilestonePrompt.seed_default_prompts()

    approved_prompts_count = MilestonePrompt.objects.filter(status='APPROVED', is_active=True).count()

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
    
    if active_role == 'STAFF':
        return redirect('/portal/admin/dashboard/?conflict=lead')

    request.session['active_admin_role'] = 'LEAD'

    platform_config = PlatformConfiguration.get_solo()

    if request.method == 'POST' and request.POST.get('action') == 'update_platform_config':
        new_fee = request.POST.get('unlock_fee', '').strip()
        annual_fee = request.POST.get('annual_subscription_fee', '').strip()
        reg_fee = (request.POST.get('registration_fee') or request.POST.get('quarterly_subscription_fee') or '').strip()
        annual_plan_code = request.POST.get('paystack_annual_plan_code', '').strip()
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

            if reg_fee:
                parsed_reg = float(reg_fee)
                if parsed_reg > 0:
                    platform_config.registration_fee = parsed_reg
                    updated_fields.append('statutory registration fee')

            if annual_plan_code:
                platform_config.paystack_annual_plan_code = annual_plan_code
                updated_fields.append('annual plan code')

            if annual_fee:
                parsed_annual = float(annual_fee)
                if parsed_annual > 0:
                    platform_config.annual_subscription_fee = parsed_annual
                    updated_fields.append('annual retainer fee')

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

            if updated_fields:
                platform_config.save()
                success_msg = f"Dashboard updated: {', '.join(updated_fields)}."
                if paystack_sync_notes:
                    success_msg += f" [{'; '.join(paystack_sync_notes)}]"
                messages.success(request, success_msg)
            else:
                messages.error(request, "No valid pricing or configuration changes were submitted.")
        except (ValueError, TypeError):
            messages.error(request, "Invalid numeric value submitted for statutory fees.")

        request.session.modified = True

    elif request.method == 'POST' and request.POST.get('action') == 'sync_paystack_plans':
        headers = {
            "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        synced_plans = []
        errors = []

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

        if synced_plans:
            platform_config.save()
            messages.success(request, f"Synced live from Paystack: {' | '.join(synced_plans)}.")
        if errors:
            messages.error(request, f"Paystack sync alerts: {', '.join(errors)}")

        request.session.modified = True

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

    # Dynamic Statutory Disbursements (Option A with Claim Precision)
    settled_policies = PolicyRecord.objects.filter(policy_status='SETTLED').prefetch_related('claims')
    total_disbursed = sum(p.statutory_disbursement_value for p in settled_policies)

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

    if active_role == 'LEAD':
        return redirect('/portal/lead-admin/?conflict=staff')

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

    new_status = request.POST.get('status')
    amount_disbursed = request.POST.get('amount_disbursed')
    insurer_notes = request.POST.get('insurer_notes', '').strip()

    valid_statuses = [choice[0] for choice in PolicyClaim.CLAIM_STATUS_CHOICES]
    if new_status not in valid_statuses:
        messages.error(request, 'Invalid claim status option.')
        return redirect('vault:staff_admin_dashboard')

    with transaction.atomic():
        claim = get_object_or_404(
            PolicyClaim.objects.select_for_update().select_related('policy'), 
            id=claim_id
        )
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

            subject = f"[mySikaVault Desk] {inquiry.get_category_display()} - {full_name}"
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
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@mysikavault.com'),
                    recipient_list=['mysikavault@gmail.com'],
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


def terms_view(request):
    """
    Public statutory Terms of Service and Platform Governance Agreement.
    """
    return render(request, 'terms.html')