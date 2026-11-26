import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { getApiErrorMessage } from "../api";
import { useAuth } from "../auth";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [usn, setUsn] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login({ usn: usn.trim(), password });
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
        <p className="eyebrow">Your campus, in play</p>
        <h1>Make room for your next game.</h1>
        <p>
          Book a court, request the equipment you need, and keep every
          reservation in one place.
        </p>
        <div className="intro-stat">
          <span className="intro-stat-icon" aria-hidden="true">↗</span>
          <span>One simple place to plan your play</span>
        </div>
      </div>

      <div className="auth-card">
        <div className="section-heading">
          <p className="eyebrow">Welcome back</p>
          <h2>Sign in</h2>
          <p>Use your student USN and password to continue.</p>
        </div>
        {location.state?.notice && (
          <div className="notice notice-success" role="status">
            {location.state.notice}
          </div>
        )}
        {error && <div className="notice notice-error" role="alert">{error}</div>}
        <form onSubmit={handleSubmit} className="form-stack">
          <label className="field">
            <span>USN</span>
            <input
              autoComplete="username"
              maxLength={50}
              name="usn"
              onChange={(event) => setUsn(event.target.value)}
              required
              value={usn}
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
