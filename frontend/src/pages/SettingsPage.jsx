import React, { useEffect, useState } from "react";
import { api, getApiErrorMessage } from "../api";
import { useAuth } from "../auth";

export default function SettingsPage() {
  const { student } = useAuth();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (student) setName(student.student_name ?? "");
  }, [student]);

  async function saveName(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const { data } = await api.updateProfile({ student_name: name.trim() });
      setEditing(false);
      setName(data.student_name);
      setNotice("Profile updated successfully.");
      window.location.reload();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError.status, requestError.body));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="settings-page">
      <section className="simple-page-heading">
        <p className="eyebrow">Account</p>
        <h1>Settings</h1>
        <p>Your student profile.</p>
      </section>
      {notice && <div className="notice notice-success" role="status">{notice}</div>}
      {error && <div className="notice notice-error" role="alert">{error}</div>}
      <section className="panel profile-panel">
        <div className="panel-heading">
          <div><h2>Student Profile</h2><p>Only your name can be changed.</p></div>
        </div>
        {editing ? (
          <form className="profile-edit-form" onSubmit={saveName}>
            <label className="field">
              <span>Name</span>
              <input aria-label="Name" maxLength={100} minLength={1} onChange={(event) => setName(event.target.value)} required value={name} />
            </label>
            <div className="inline-actions">
              <button className="button button-primary" disabled={saving || !name.trim()} type="submit">{saving ? "Saving…" : "Save Changes"}</button>
              <button className="button button-quiet" onClick={() => { setEditing(false); setName(student?.student_name ?? ""); }} type="button">Cancel</button>
            </div>
          </form>
        ) : (
          <dl className="profile-list">
            <div><dt>Name</dt><dd>{student?.student_name}</dd></div>
            <div><dt>Email</dt><dd>{student?.college_email}</dd></div>
            <div><dt>USN</dt><dd>{student?.usn}</dd></div>
            <div><dt>Phone Number</dt><dd>{student?.phone_number}</dd></div>
            <div><dt>Branch</dt><dd>{student?.branch}</dd></div>
          </dl>
        )}
        {!editing && <button className="button button-primary" onClick={() => setEditing(true)} type="button">Edit Name</button>}
      </section>
    </div>
  );
}
