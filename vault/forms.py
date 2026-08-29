from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import (
    CustomUser,
    EmergencyContact,
    PolicyRecord,
    AssetRecord,
    EstateDocument,
)


class SignUpForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = [
            'username',
            'first_name',
            'last_name',
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
        if 'password1' in self.fields:
            self.fields['password1'].widget.attrs.update({'class': 'auth-input', 'placeholder': 'Create strong password'})
        if 'password2' in self.fields:
            self.fields['password2'].widget.attrs.update({'class': 'auth-input', 'placeholder': 'Confirm password'})


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'phone_number', 'ghana_card_number', 'permanent_address']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Last Name'}),
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


class PolicyRecordForm(forms.ModelForm):
    class Meta:
        model = PolicyRecord
        fields = ['insurer', 'policy_number', 'policy_type', 'is_active']
        widgets = {
            'insurer': forms.Select(attrs={'class': 'form-input'}),
            'policy_number': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Policy / Certificate ID'}),
            'policy_type': forms.Select(attrs={'class': 'form-input'}),
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