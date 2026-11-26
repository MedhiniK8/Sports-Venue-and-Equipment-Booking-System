import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, getApiErrorMessage } from "../api";

const initialForm = {
  usn: "",
  password: "",
  confirmPassword: "",
  collegeEmail: "",
  phoneNumber: "",
  yearOfAdmission: "",
  gender: "",
  branch: "",
};

export default function RegistrationPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState(initialForm);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function updateField(event) {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    if (form.password !== form.confirmPassword) {
      setError("Password and confirm password must match.");
      return;
    }

    setSubmitting(true);
    try {
      await api.register({
        usn: form.usn.trim(),
        password: form.password,
        confirm_password: form.confirmPassword,
        college_email: form.collegeEmail.trim().toLowerCase(),
        phone_number: form.phoneNumber.trim(),
        year_of_admission: Number(form.yearOfAdmission),
        gender: form.gender.trim(),
        branch: form.branch.trim(),
      });
      navigate("/login", {
        replace: true,
        state: { notice: "Account created. Sign in to start booking." },
      });
    } catch (requestError) {
      setError(getApiErrorMessage(requestError.status, requestError.body));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="auth-layout auth-layout-registration">
      <div className="auth-intro">
        <p className="eyebrow">Join the community</p>
        <h1>Your next match starts here.</h1>
        <p>Create your student account to discover campus sports and manage bookings.</p>
        <div className="intro-stat">
          <span className="intro-stat-icon" aria-hidden="true">✦</span>
          <span>Register once, book whenever you’re ready</span>
        </div>
      </div>

      <div className="auth-card registration-card">
        <div className="section-heading">
          <p className="eyebrow">Student account</p>
          <h2>Create your account</h2>
          <p>All fields are required. You’ll sign in after registration.</p>
        </div>
        {error && <div className="notice notice-error" role="alert">{error}</div>}
        <form onSubmit={handleSubmit} className="form-stack">
          <div className="field-grid">
            <label className="field">
              <span>USN</span>
              <input autoComplete="username" maxLength={50} name="usn" onChange={updateField} required value={form.usn} />
            </label>
            <label className="field">
              <span>College email</span>
              <input autoComplete="email" maxLength={254} name="collegeEmail" onChange={updateField} required type="email" value={form.collegeEmail} />
            </label>
            <label className="field">
              <span>Password</span>
              <input autoComplete="new-password" maxLength={128} minLength={8} name="password" onChange={updateField} required type="password" value={form.password} />
            </label>
            <label className="field">
              <span>Confirm password</span>
              <input autoComplete="new-password" maxLength={128} minLength={8} name="confirmPassword" onChange={updateField} required type="password" value={form.confirmPassword} />
            </label>
            <label className="field">
              <span>Phone number</span>
              <input autoComplete="tel" maxLength={32} name="phoneNumber" onChange={updateField} required value={form.phoneNumber} />
            </label>
            <label className="field">
              <span>Year of admission</span>
              <input min="1" name="yearOfAdmission" onChange={updateField} required type="number" value={form.yearOfAdmission} />
            </label>
            <label className="field">
              <span>Gender</span>
              <input maxLength={32} name="gender" onChange={updateField} required value={form.gender} />
            </label>
            <label className="field">
              <span>Branch</span>
              <input maxLength={100} name="branch" onChange={updateField} required value={form.branch} />
            </label>
          </div>
          <button className="button button-primary button-wide" disabled={submitting}>
            {submitting ? "Creating account…" : "Create account"}
          </button>
        </form>
        <p className="auth-switch">
          Already registered? <Link to="/login">Sign in</Link>
        </p>
      </div>
    </section>
  );
}
