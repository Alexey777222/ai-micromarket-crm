from django import forms

from .models import DeviceProvider


class SalesImportForm(forms.Form):
    provider = forms.ModelChoiceField(queryset=DeviceProvider.objects.none(), label="Поставщик")
    file = forms.FileField(label="CSV-файл")

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields["provider"].queryset = DeviceProvider.objects.filter(
                organization=organization, is_active=True
            )

    def clean_file(self):
        file = self.cleaned_data["file"]
        if file.size > 10 * 1024 * 1024:
            raise forms.ValidationError("Максимальный размер файла — 10 МБ.")
        if not file.name.lower().endswith(".csv"):
            raise forms.ValidationError("Разрешены только CSV-файлы.")
        return file
