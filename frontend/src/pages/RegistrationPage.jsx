import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, getApiErrorMessage } from "../api";

const initialForm = {
  studentName: "",
  usn: "",
  password: "",
  confirmPassword: "",
  collegeEmail: "",
  phoneNumber: "",
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
        student_name: form.studentName.trim(),
        usn: form.usn.trim(),
        password: form.password,
        confirm_password: form.confirmPassword,
        college_email: form.collegeEmail.trim().toLowerCase(),
        phone_number: form.phoneNumber.trim(),
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
        <img alt="" className="auth-logo" src="/images/branding/sportshub-logo.svg" />
        <div className="auth-intro-copy">
          <h1><span>Play More.</span><strong>Wait Less.</strong></h1>
          <p>
            Book courts and equipment easily for your favourite sports and
            make the most of your campus sports facilities.
          </p>
        </div>
      </div>

      <div className="auth-card registration-card">
        <div className="auth-tabs" aria-label="Authentication type">
          <Link className="auth-tab" to="/login">Login</Link>
          <Link className="auth-tab is-active" to="/register">Register</Link>
        </div>
        <div className="section-heading">
          <p className="eyebrow">Student account</p>
          <h2>Create your account</h2>
          <p>All fields are required. You’ll sign in after registration.</p>
        </div>
        {error && <div className="notice notice-error" role="alert">{error}</div>}
        <form onSubmit={handleSubmit} className="form-stack">
          <div className="field-grid">
            <label className="field">
              <span>Name</span>
              <input autoComplete="name" maxLength={100} name="studentName" onChange={updateField} required value={form.studentName} />
            </label>
            <label className="field">
              <span>Email</span>
              <input autoComplete="email" maxLength={254} name="collegeEmail" onChange={updateField} required type="email" value={form.collegeEmail} />
            </label>
            <label className="field">
              <span>USN</span>
              <input autoComplete="username" maxLength={50} name="usn" onChange={updateField} required value={form.usn} />
            </label>
            <label className="field">
              <span>Phone Number</span>
              <input autoComplete="tel" maxLength={32} name="phoneNumber" onChange={updateField} required value={form.phoneNumber} />
            </label>
            <label className="field">
              <span>Branch</span>
              <input maxLength={100} name="branch" onChange={updateField} required value={form.branch} />
            </label>
            <label className="field">
              <span>Password</span>
              <input autoComplete="new-password" maxLength={128} minLength={8} name="password" onChange={updateField} required type="password" value={form.password} />
            </label>
            <label className="field">
              <span>Confirm Password</span>
              <input autoComplete="new-password" maxLength={128} minLength={8} name="confirmPassword" onChange={updateField} required type="password" value={form.confirmPassword} />
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
