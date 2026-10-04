# FHIR import example

`combination_suspension.json` is a synthetic integration example, not a patient record or a
real-world benchmark case. It contains one active FHIR R4 MedicationRequest with a contained
Medication, explicit ingredient concentrations, a 5 mL dose twice daily for 5 days, and an
oral route. Ingredients deliberately arrive in reverse order to demonstrate correct component
mapping. Patient weight, age, allergies and medicines must be supplied separately.

In the app, choose **FHIR prescription**, select this file, check the preview, and attach a
medicine photo. Imported values carry JSON-path evidence; the bottle uses the same perception,
OCR and reliability gates as a photographed prescription.

Supported input is one fixed order in a MedicationRequest or a local Bundle. PRN, tapers,
ranges, rates, free-text conditions, dose limits, unknown modifier extensions and unresolved
remote medication references are rejected. An absent treatment duration remains missing.
This importer copies supplied structured facts; it does not authenticate an order or validate
all of FHIR R4. MedicationDispense integration is still future work.
