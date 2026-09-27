/**
 * Register a patient (POST /api/patients). Client-side checks mirror the backend's rules so mistakes are caught
 * early, but the backend stays authoritative: its 422 field errors are shown on the matching fields and a 409
 * (possible duplicate) is shown prominently with the existing Patient IDs it reports.
 */
import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, fieldErrors } from '../../api/client'
import { patientsApi } from '../../api/endpoints'
import type { PatientCreate, Sex } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import { Alert, Button, Card, EmptyState, Field, Input, LinkButton, PageHeader, Select } from '../../components/ui'
import { patientDisplayName } from '../../lib/format'
import './patients.css'

type FormState = Record<keyof PatientCreate, string>

const EMPTY: FormState = {
  first_name: '', middle_name: '', last_name: '', date_of_birth: '', sex: '', phone: '', email: '',
  address_line1: '', address_line2: '', city: '', state_province: '', postal_code: '', country: '',
  emergency_contact_name: '', emergency_contact_relationship: '', emergency_contact_phone: '',
}

const PHONE = /^(\+[1-9][0-9]{6,14}|[0-9]{7,15})$/
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

function todayIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function validate(form: FormState): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!form.first_name.trim()) errors.first_name = 'Enter the first name.'
  if (!form.last_name.trim()) errors.last_name = 'Enter the last name.'
  if (!form.sex) errors.sex = 'Select the sex recorded for the patient.'
  if (!form.date_of_birth) errors.date_of_birth = 'Enter the date of birth.'
  else if (form.date_of_birth > todayIso()) errors.date_of_birth = 'Date of birth cannot be in the future.'
  else if (form.date_of_birth < '1900-01-01') errors.date_of_birth = 'Date of birth cannot be before 1900.'
  for (const field of ['phone', 'emergency_contact_phone'] as const) {
    const compact = form[field].replace(/[\s\-().]/g, '').replace(/^00/, '+')
    if (form[field].trim() && !PHONE.test(compact)) {
      errors[field] = 'Use an international number (+ country code) or a 7–15 digit national number.'
    }
  }
  if (form.email.trim() && !EMAIL.test(form.email.trim())) errors.email = 'Enter a valid email address.'
  return errors
}

function toPayload(form: FormState): PatientCreate {
  const optional = (value: string) => (value.trim() ? value.trim() : null)
  return {
    first_name: form.first_name.trim(), middle_name: optional(form.middle_name), last_name: form.last_name.trim(),
    date_of_birth: form.date_of_birth, sex: form.sex as Sex, phone: optional(form.phone), email: optional(form.email),
    address_line1: optional(form.address_line1), address_line2: optional(form.address_line2), city: optional(form.city),
    state_province: optional(form.state_province), postal_code: optional(form.postal_code), country: optional(form.country),
    emergency_contact_name: optional(form.emergency_contact_name),
    emergency_contact_relationship: optional(form.emergency_contact_relationship),
    emergency_contact_phone: optional(form.emergency_contact_phone),
  }
}

export function RegisterPatientPage() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState<FormState>(EMPTY)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<{ tone: 'danger' | 'warning'; title: string; message: string } | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const crumbs = [{ label: 'Dashboard', to: '/' }, { label: 'Patients', to: '/patients' }, { label: 'Register patient' }]
  if (!can('patient.create')) {
    return (
      <>
        <PageHeader title="Register patient" breadcrumbs={crumbs} />
        <Card><EmptyState icon="lock" title="Not available for your role"
          description="Registering patients requires the patient.create permission." /></Card>
      </>
    )
  }

  const set = (field: keyof FormState) => (event: { target: { value: string } }) => {
    setForm((f) => ({ ...f, [field]: event.target.value }))
    if (errors[field]) setErrors((e) => { const next = { ...e }; delete next[field]; return next })
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const clientErrors = validate(form)
    setErrors(clientErrors)
    setFormError(null)
    if (Object.keys(clientErrors).length > 0) {
      setFormError({ tone: 'danger', title: 'Please correct the highlighted fields', message: 'The patient has not been registered yet.' })
      return
    }
    setSubmitting(true)
    try {
      const created = await patientsApi.create(toPayload(form))
      navigate(`/patients/${created.id}`, { replace: true, state: { notice: `${patientDisplayName(created)} registered as ${created.patient_number}.` } })
    } catch (err) {
      const serverErrors = fieldErrors(err)
      setErrors(serverErrors)
      if (err instanceof ApiError && err.status === 409) {
        setFormError({ tone: 'warning', title: 'Possible duplicate patient', message: err.message })
      } else if (Object.keys(serverErrors).length > 0) {
        setFormError({ tone: 'danger', title: 'Please correct the highlighted fields', message: 'The HMS rejected some values.' })
      } else {
        setFormError({ tone: 'danger', title: 'Registration failed', message: err instanceof ApiError ? err.message : 'Please try again.' })
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <PageHeader title="Register patient" breadcrumbs={crumbs}
        description="Create a new patient record. A Patient ID is assigned automatically." />
      <form className="form-layout" onSubmit={onSubmit} noValidate>
        {formError ? <Alert tone={formError.tone} title={formError.title}>{formError.message}</Alert> : null}

        <Card title="Identity" description="Required details used to identify the patient">
          <div className="form-grid form-grid--3">
            <Field label="First name" required error={errors.first_name}><Input value={form.first_name} onChange={set('first_name')} autoComplete="off" maxLength={100} /></Field>
            <Field label="Middle name" error={errors.middle_name}><Input value={form.middle_name} onChange={set('middle_name')} autoComplete="off" maxLength={100} /></Field>
            <Field label="Last name" required error={errors.last_name}><Input value={form.last_name} onChange={set('last_name')} autoComplete="off" maxLength={100} /></Field>
            <Field label="Date of birth" required error={errors.date_of_birth}>
              <Input type="date" value={form.date_of_birth} onChange={set('date_of_birth')} min="1900-01-01" max={todayIso()} />
            </Field>
            <Field label="Sex" required error={errors.sex}>
              <Select value={form.sex} onChange={set('sex')}>
                <option value="" disabled>Select…</option>
                <option value="FEMALE">Female</option>
                <option value="MALE">Male</option>
                <option value="OTHER">Other</option>
                <option value="UNKNOWN">Unknown</option>
              </Select>
            </Field>
          </div>
        </Card>

        <Card title="Contact" description="Optional">
          <div className="form-grid">
            <Field label="Phone" hint="International (+254…) or national number" error={errors.phone}>
              <Input type="tel" value={form.phone} onChange={set('phone')} autoComplete="off" maxLength={30} />
            </Field>
            <Field label="Email" error={errors.email}><Input type="email" value={form.email} onChange={set('email')} autoComplete="off" maxLength={254} /></Field>
            <div className="form-grid__wide"><Field label="Address line 1" error={errors.address_line1}><Input value={form.address_line1} onChange={set('address_line1')} maxLength={200} /></Field></div>
            <div className="form-grid__wide"><Field label="Address line 2" error={errors.address_line2}><Input value={form.address_line2} onChange={set('address_line2')} maxLength={200} /></Field></div>
            <Field label="City / town" error={errors.city}><Input value={form.city} onChange={set('city')} maxLength={100} /></Field>
            <Field label="County / state" error={errors.state_province}><Input value={form.state_province} onChange={set('state_province')} maxLength={100} /></Field>
            <Field label="Postal code" error={errors.postal_code}><Input value={form.postal_code} onChange={set('postal_code')} maxLength={20} /></Field>
            <Field label="Country" error={errors.country}><Input value={form.country} onChange={set('country')} maxLength={100} /></Field>
          </div>
        </Card>

        <Card title="Emergency contact" description="Optional">
          <div className="form-grid form-grid--3">
            <Field label="Name" error={errors.emergency_contact_name}><Input value={form.emergency_contact_name} onChange={set('emergency_contact_name')} maxLength={200} /></Field>
            <Field label="Relationship" error={errors.emergency_contact_relationship}><Input value={form.emergency_contact_relationship} onChange={set('emergency_contact_relationship')} maxLength={50} /></Field>
            <Field label="Phone" error={errors.emergency_contact_phone}><Input type="tel" value={form.emergency_contact_phone} onChange={set('emergency_contact_phone')} maxLength={30} /></Field>
          </div>
        </Card>

        <div className="form-actions">
          <LinkButton to="/patients" variant="secondary">Cancel</LinkButton>
          <Button type="submit" variant="primary" loading={submitting} icon="plus">Register patient</Button>
        </div>
      </form>
    </>
  )
}
