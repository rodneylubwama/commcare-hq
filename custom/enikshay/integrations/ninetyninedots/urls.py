from django.conf.urls import url
from custom.enikshay.integrations.ninetyninedots.views import (
    RegisterPatientRepeaterView,
    UpdatePatientRepeaterView,
    UpdateAdherenceRepeaterView,
    UpdateTreatmentOutcomeRepeaterView,
    update_patient_adherence,
    update_adherence_confidence,
    update_default_confidence,
)

urlpatterns = [
    url(r'^update_patient_adherence$', update_patient_adherence, name='update_patient_adherence'),
    url(r'^update_adherence_confidence$', update_adherence_confidence, name='update_adherence_confidence'),
    url(r'^update_default_confidence$', update_default_confidence, name='update_default_confidence'),
    url(
        r'^new_register_patient_repeater$',
        RegisterPatientRepeaterView.as_view(),
        {'repeater_type': 'NinetyNineDotsRegisterPatientRepeater'},
        name=RegisterPatientRepeaterView.urlname
    ),
    url(
        r'^new_update_patient_repeater$',
        UpdatePatientRepeaterView.as_view(),
        {'repeater_type': 'NinetyNineDotsUpdatePatientRepeater'},
        name=UpdatePatientRepeaterView.urlname
    ),
    url(
        r'^new_update_adherence_repeater$',
        UpdateAdherenceRepeaterView.as_view(),
        {'repeater_type': 'NinetyNineDotsAdherenceRepeater'},
        name=UpdateAdherenceRepeaterView.urlname
    ),
    url(
        r'^new_update_treatment_outcome_repeater$',
        UpdateAdherenceRepeaterView.as_view(),
        {'repeater_type': 'NinetyNineDotsTreatmentOutcomeRepeater'},
        name=UpdateTreatmentOutcomeRepeaterView.urlname
    ),
]
