import re
from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import (
    AssetRecord,
    CitizenMemory,
    CustomUser,
    EmergencyContact,
    EstateDocument,
    FamilyMember,
    MilestonePrompt,
    PlatformConfiguration,
    PolicyRecord,
    SecurityQuestion,
    UserSecurityAnswer,
)


class SignUpForm(UserCreationForm):
    VERIFICATION_METHOD_CHOICES = (
        ('QUESTIONS', 'Instant Activation via Security Questions'),
        ('EMAIL', 'Verify via Email Confirmation Link'),
    )

    verification_method = forms.ChoiceField(
        choices=VERIFICATION_METHOD_CHOICES,
        initial='QUESTIONS',
        widget=forms.RadioSelect(attrs={'class': 'verification-radio'}),
        help_text="Select your statutory vault verification and activation protocol."
    )

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'auth-input',
            'placeholder': 'kwame.mensah@gmail.com',
            'required': 'required',
        })
    )

    class Meta:
        model = CustomUser
        fields = [
            'username',
            'first_name',
            'last_name',
            'email',
            'phone_number',
            'ghana_card_number',
            'permanent_address',
        ]
        widgets = {
            'username': forms.TextInput(attrs={'class': 'auth-input', 'placeholder': 'Choose username'}),
            'first_name': forms.TextInput(attrs={'class': 'auth-input', 'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'class': 'auth-input', 'placeholder': 'Last Name'}),
            'phone_number': forms.TextInput(attrs={'class': 'auth-input', 'placeholder': '024 XXX XXXX'}),
            'ghana_card_number': forms.TextInput(attrs={'class': 'auth-input', 'placeholder': 'GHA-XXXXXXXXX-X'}),
            'permanent_address': forms.Textarea(attrs={'class': 'auth-input', 'rows': 2, 'placeholder': 'Digital GPS / Permanent Address'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not SecurityQuestion.objects.exists():
            SecurityQuestion.seed_default_questions()

        config = PlatformConfiguration.get_solo()
        self.required_questions_count = config.required_security_questions if config else 3
        active_questions = SecurityQuestion.objects.filter(is_active=True).order_by('display_order', 'id')

        # Dynamically inject the exact number of questions defined by admin
        for i in range(1, self.required_questions_count + 1):
            self.fields[f'question_{i}'] = forms.ModelChoiceField(
                queryset=active_questions,
                required=False,
                empty_label=f"-- Select Security Question {i} --",
                widget=forms.Select(attrs={'class': 'auth-input sec-question-select'})
            )
            self.fields[f'answer_{i}'] = forms.CharField(
                required=False,
                widget=forms.TextInput(attrs={'class': 'auth-input', 'placeholder': f'Answer to Question {i}'})
            )

        core_fields = [
            'username', 'first_name', 'last_name', 'email', 
            'phone_number', 'ghana_card_number', 'permanent_address', 'verification_method'
        ]
        for name in core_fields:
            if name in self.fields:
                self.fields[name].required = True
                self.fields[name].widget.attrs['required'] = 'required'

        if 'password1' in self.fields:
            self.fields['password1'].widget.attrs.update({
                'class': 'auth-input',
                'placeholder': 'Create strong password (min 8 chars)',
                'minlength': '8',
            })
        if 'password2' in self.fields:
            self.fields['password2'].widget.attrs.update({
                'class': 'auth-input',
                'placeholder': 'Confirm password',
                'minlength': '8',
            })

    @property
    def security_question_fields(self):
        """Pairs question and answer bound fields for clean template looping."""
        field_pairs = []
        for i in range(1, getattr(self, 'required_questions_count', 3) + 1):
            q_name = f'question_{i}'
            a_name = f'answer_{i}'
            if q_name in self.fields and a_name in self.fields:
                field_pairs.append({
                    'index': i,
                    'question': self[q_name],
                    'answer': self[a_name],
                })
        return field_pairs

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            email = email.strip().lower()
            if CustomUser.objects.filter(email__iexact=email).exists():
                raise forms.ValidationError('An account with this email address already exists.')
            return email
        raise forms.ValidationError('A valid email address is required for vault billing and Paystack receipts.')

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number', '').strip()
        cleaned_digits = re.sub(r'\D', '', phone)

        if not cleaned_digits:
            raise forms.ValidationError('A valid mobile phone number is required.')

        if len(cleaned_digits) < 9 or len(cleaned_digits) > 13:
            raise forms.ValidationError('Please enter a valid mobile number (e.g. 0244123456 or +233244123456).')

        return phone

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('verification_method')

        if method == 'QUESTIONS':
            selected_ids = []
            for i in range(1, getattr(self, 'required_questions_count', 3) + 1):
                q = cleaned_data.get(f'question_{i}')
                a = (cleaned_data.get(f'answer_{i}') or '').strip()

                if not q or not a:
                    self.add_error(f'answer_{i}', f'Please select Question {i} and provide an answer.')
                if q:
                    selected_ids.append(q.id)

            if len(selected_ids) == getattr(self, 'required_questions_count', 3):
                if len(set(selected_ids)) < len(selected_ids):
                    raise forms.ValidationError(
                        f'Please choose {self.required_questions_count} distinct questions. You cannot select the same question twice.'
                    )

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        method = self.cleaned_data.get('verification_method')

        if method == 'QUESTIONS':
            user.is_active = True
        else:
            user.is_active = False

        if commit:
            user.save()
            if method == 'QUESTIONS':
                for i in range(1, getattr(self, 'required_questions_count', 3) + 1):
                    q = self.cleaned_data.get(f'question_{i}')
                    a = self.cleaned_data.get(f'answer_{i}')
                    if q and a:
                        UserSecurityAnswer.objects.update_or_create(
                            user=user,
                            question=q,
                            defaults={'answer': a.strip()}
                        )
        return user

class SecurityQuestionsSetupForm(forms.Form):
    """
    Mandatory dynamic setup form displayed after an unverified citizen clicks their email activation link.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not SecurityQuestion.objects.exists():
            SecurityQuestion.seed_default_questions()

        config = PlatformConfiguration.get_solo()
        self.required_questions_count = config.required_security_questions if config else 3
        active_questions = SecurityQuestion.objects.filter(is_active=True).order_by('display_order', 'id')

        for i in range(1, self.required_questions_count + 1):
            self.fields[f'question_{i}'] = forms.ModelChoiceField(
                queryset=active_questions,
                empty_label=f"-- Select Security Question {i} --",
                widget=forms.Select(attrs={'class': 'sec-select-field', 'required': 'required'})
            )
            self.fields[f'answer_{i}'] = forms.CharField(
                widget=forms.TextInput(attrs={
                    'class': 'sec-text-field',
                    'placeholder': f'Enter your confidential answer for key {i}...',
                    'required': 'required',
                    'autocomplete': 'off',
                })
            )

    @property
    def security_question_fields(self):
        """Pairs question and answer bound fields for clean template looping."""
        field_pairs = []
        for i in range(1, getattr(self, 'required_questions_count', 3) + 1):
            q_name = f'question_{i}'
            a_name = f'answer_{i}'
            if q_name in self.fields and a_name in self.fields:
                field_pairs.append({
                    'index': i,
                    'question': self[q_name],
                    'answer': self[a_name],
                })
        return field_pairs

    def clean(self):
        cleaned_data = super().clean()
        selected_ids = []

        for i in range(1, getattr(self, 'required_questions_count', 3) + 1):
            q = cleaned_data.get(f'question_{i}')
            a = (cleaned_data.get(f'answer_{i}') or '').strip()

            if not q or not a:
                self.add_error(f'answer_{i}', f'Please select Question {i} and provide an answer.')
            if q:
                selected_ids.append(q.id)

        if len(selected_ids) == getattr(self, 'required_questions_count', 3):
            if len(set(selected_ids)) < len(selected_ids):
                raise forms.ValidationError(
                    f'Please choose {self.required_questions_count} distinct questions. You cannot select the same question twice.'
                )

        return cleaned_data

    def save(self, user):
        for i in range(1, getattr(self, 'required_questions_count', 3) + 1):
            q = self.cleaned_data.get(f'question_{i}')
            a = self.cleaned_data.get(f'answer_{i}')
            if q and a:
                UserSecurityAnswer.objects.update_or_create(
                    user=user,
                    question=q,
                    defaults={'answer': a.strip()}
                )
        return user

class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'ghana_card_number', 'permanent_address']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Last Name'}),
            'email': forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'Email Address'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-input', 'placeholder': '024 XXX XXXX'}),
            'ghana_card_number': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'GHA-XXXXXXXXX-X'}),
            'permanent_address': forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'placeholder': 'Digital GPS / Physical Address'}),
        }


class EmergencyContactForm(forms.ModelForm):
    class Meta:
        model = EmergencyContact
        fields = ['full_name', 'relationship', 'phone_number', 'email', 'is_primary']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Contact Full Name'}),
            'relationship': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Spouse, Brother, Next of Kin'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Phone Number'}),
            'email': forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'Email Address (Optional)'}),
        }

    def clean_phone_number(self):
        phone = self.cleaned_data.get('phone_number', '').strip()
        digits = re.sub(r'\D', '', phone)

        if not digits:
            raise forms.ValidationError('A valid phone number is required.')

        if len(digits) < 9 or len(digits) > 13:
            raise forms.ValidationError('Please enter a valid phone number (e.g. 0244123456 or +233244123456).')

        clean_digits = digits[-9:]

        # Global Option B check: across all next-of-kin contacts and citizen accounts
        contacts_exist = EmergencyContact.objects.filter(phone_number__endswith=clean_digits)
        if self.instance and self.instance.pk:
            contacts_exist = contacts_exist.exclude(pk=self.instance.pk)

        if contacts_exist.exists() or CustomUser.objects.filter(phone_number__endswith=clean_digits).exists():
            raise forms.ValidationError('This phone number is already registered in the system. Please use a different contact number.')

        return phone

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            email = email.strip().lower()
            contacts_exist = EmergencyContact.objects.filter(email__iexact=email)
            if self.instance and self.instance.pk:
                contacts_exist = contacts_exist.exclude(pk=self.instance.pk)

            if contacts_exist.exists() or CustomUser.objects.filter(email__iexact=email).exists():
                raise forms.ValidationError('This email address is already registered in the system. Please provide a different email address.')
            return email
        return email


class PolicyRecordForm(forms.ModelForm):
    class Meta:
        model = PolicyRecord
        fields = ['insurer', 'policy_number', 'policy_type', 'sum_assured', 'is_active']
        widgets = {
            'insurer': forms.Select(attrs={'class': 'form-input'}),
            'policy_number': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Policy / Certificate ID'}),
            'policy_type': forms.Select(attrs={'class': 'form-input'}),
            'sum_assured': forms.NumberInput(attrs={'class': 'form-input', 'placeholder': 'e.g. 50000.00', 'step': '0.01'}),
        }


class AssetRecordForm(forms.ModelForm):
    class Meta:
        model = AssetRecord
        fields = ['asset_type', 'title', 'estimated_value', 'location_or_identifier', 'document_proof']
        widgets = {
            'asset_type': forms.Select(attrs={'class': 'form-input'}),
            'title': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. 2 Plots at East Legon, Toyota Prado'}),
            'estimated_value': forms.NumberInput(attrs={'class': 'form-input', 'placeholder': 'GHS Value'}),
            'location_or_identifier': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Location / Reg Plate / Account No.'}),
            'document_proof': forms.FileInput(attrs={'class': 'form-input-file'}),
        }


class EstateDocumentForm(forms.ModelForm):
    class Meta:
        model = EstateDocument
        fields = ['document_type', 'title', 'document_file', 'notes']
        widgets = {
            'document_type': forms.Select(attrs={'class': 'form-input'}),
            'title': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Last Will & Testament 2026'}),
            'document_file': forms.FileInput(attrs={'class': 'form-input-file'}),
            'notes': forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'Depository notes or lawyer contact'}),
        }


class CitizenMemoryForm(forms.ModelForm):
    """
    Intake form for policyholders to deposit milestone memories and photos into their time capsule.
    """
    class Meta:
        model = CitizenMemory
        fields = ['prompt', 'story_or_answer', 'approximate_year_or_era', 'photo']
        widgets = {
            'prompt': forms.Select(attrs={'class': 'form-input', 'required': 'required'}),
            'story_or_answer': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 3,
                'placeholder': 'Share the story, names, places, or personal details...',
                'required': 'required',
            }),
            'approximate_year_or_era': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Circa 1994, Summer 2005, Class of 2012',
            }),
            'photo': forms.FileInput(attrs={'class': 'form-input-file', 'accept': 'image/*'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only present milestones that have been reviewed and approved by administrators
        self.fields['prompt'].queryset = MilestonePrompt.objects.filter(
            status='APPROVED',
            is_active=True
        ).order_by('category', 'display_order', 'title')
        self.fields['prompt'].empty_label = "-- Select an Admin-Approved Milestone --"

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if photo:
            # Enforce 8MB file size limit to preserve vault bandwidth and storage
            if photo.size > 8 * 1024 * 1024:
                raise forms.ValidationError("Attached photo exceeds the 8MB statutory size limit. Please upload a compressed image.")
        return photo


class MilestoneSuggestionForm(forms.ModelForm):
    """
    Allows citizens to suggest new milestone prompts to the Lead and Django Admins.
    """
    class Meta:
        model = MilestonePrompt
        fields = ['title', 'category']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. First Family Trip Abroad, First Business Venture',
                'required': 'required',
            }),
            'category': forms.Select(attrs={'class': 'form-input', 'required': 'required'}),
        }

    def clean_title(self):
        title = self.cleaned_data.get('title', '').strip()
        if MilestonePrompt.objects.filter(title__iexact=title).exists():
            raise forms.ValidationError("A milestone prompt with this title already exists in the registry.")
        return title


class FamilyMemberForm(forms.ModelForm):
    """
    Intake form for building the generational family tree inside the policyholder vault.
    """
    class Meta:
        model = FamilyMember
        fields = [
            'relationship',
            'full_name',
            'maiden_name',
            'birth_year',
            'birth_place',
            'photo',
            'bio_notes',
            'linked_emergency_contact',
        ]
        widgets = {
            'relationship': forms.Select(attrs={'class': 'form-input', 'required': 'required'}),
            'full_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Full legal or ancestral name', 'required': 'required'}),
            'maiden_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Maiden surname (optional)'}),
            'birth_year': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. 1962 or May 1962'}),
            'birth_place': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Town / City of origin (e.g. Kumasi, Cape Coast)'}),
            'photo': forms.FileInput(attrs={'class': 'form-input-file', 'accept': 'image/*'}),
            'bio_notes': forms.Textarea(attrs={'class': 'form-input', 'rows': 2, 'placeholder': 'Notable memories, clan, or life achievements'}),
            'linked_emergency_contact': forms.Select(attrs={'class': 'form-input'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            # Restrict emergency contact linkage strictly to the active citizen's own next-of-kin contacts
            self.fields['linked_emergency_contact'].queryset = EmergencyContact.objects.filter(user=user)
        self.fields['linked_emergency_contact'].empty_label = "-- Not linked to statutory contact (Optional) --"