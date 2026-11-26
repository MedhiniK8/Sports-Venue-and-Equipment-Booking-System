import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { getApiErrorMessage } from "../api";
import { useAuth } from "../auth";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login({ identifier: identifier.trim(), password });
      navigate("/", { replace: true });
    } catch (requestError) {
      setError(getApiErrorMessage(requestError.status, requestError.body));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="auth-layout">
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

      <div className="auth-card">
        <div className="auth-tabs" aria-label="Authentication type">
          <Link className="auth-tab is-active" to="/login">Login</Link>
          <Link className="auth-tab" to="/register">Register</Link>
        </div>
        <div className="section-heading">
          <p className="eyebrow">Welcome back</p>
          <h2>Sign in</h2>
          <p>Use your student USN or college email and password to continue.</p>
        </div>
        {location.state?.notice && (
          <div className="notice notice-success" role="status">
            {location.state.notice}
          </div>
        )}
        {error && <div className="notice notice-error" role="alert">{error}</div>}
        <form onSubmit={handleSubmit} className="form-stack">
          <label className="field">
            <span>USN or college email</span>
            <input
              autoComplete="username"
              maxLength={254}
              name="identifier"
              onChange={(event) => setIdentifier(event.target.value)}
              required
              value={identifier}
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              autoComplete="current-password"
              maxLength={128}
              name="password"
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </label>
          <button className="button button-primary button-wide" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="auth-switch">
          New to campus booking? <Link to="/register">Create an account</Link>
        </p>
      </div>
    </section>
  );
}
