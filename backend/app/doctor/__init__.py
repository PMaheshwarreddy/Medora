"""The doctor portal: the patient queue, the doctor's review of Medora's
report, and the signed final report the patient receives.

Doctors sign in with their hospital account (`app/hospital/`, role
`doctor`). The AI report is never changed: the doctor's decisions are kept
beside it in `DoctorReview`, so what the AI suggested and what the doctor
decided can always both be seen.
"""
