import React, { useEffect, useState } from "react";
import { api, getApiErrorMessage } from "../api";

export default function AdminPage() {
  const [courts, setCourts] = useState([]);
  const [sports, setSports] = useState([]);
  const [blockOuts, setBlockOuts] = useState([]);
  const [form, setForm] = useState({
    court_id: "",
    starts_at: "",
    ends_at: "",
    reason: "",
  });
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    setError("");
    try {
      const [sportsResponse, blockResponse] = await Promise.all([
        api.getSports(),
        api.getBlockOuts(),
      ]);
      setSports(sportsResponse.data);
      setBlockOuts(blockResponse.data);
      const courtResponses = await Promise.all(
        sportsResponse.data.map((sport) => api.getCourts(sport.sport_id)),
      );
      setCourts(courtResponses.flatMap((response) => response.data));
    } catch (requestError) {
      setError(getApiErrorMessage(requestError.status, requestError.body));
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function createBlockOut(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      await api.createBlockOut({
        court_id: form.court_id,
        starts_at: form.starts_at,
        ends_at: form.ends_at,
        reason: form.reason || null,
      });
      setNotice("Block-out created.");
      setForm({ court_id: "", starts_at: "", ends_at: "", reason: "" });
      await refresh();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError.status, requestError.body));
    }
  }

  async function deactivate(blockOutId) {
    setError("");
    setNotice("");
    try {
      await api.deactivateBlockOut(blockOutId);
      setNotice("Block-out deactivated.");
      await refresh();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError.status, requestError.body));
    }
  }

  return (
    <div className="dashboard-page">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Administration</p>
          <h1>Admin dashboard</h1>
          <p>View courts and manage court block-outs.</p>
        </div>
      </section>
      {notice && <div className="notice notice-success" role="status">{notice}</div>}
      {error && <div className="notice notice-error" role="alert">{error}</div>}
      <section className="panel">
        <div className="panel-heading">
          <span className="step-number">01</span>
          <div>
            <h2>Create block-out</h2>
            <p>Intervals must be within 06:00–20:00.</p>
          </div>
        </div>
        <form className="form-stack" onSubmit={createBlockOut}>
          <div className="field-grid">
            <label className="field">
              <span>Court</span>
              <select
                onChange={(event) => setForm((current) => ({
                  ...current,
                  court_id: event.target.value,
                }))}
                required
                value={form.court_id}
              >
                <option value="">Select a court</option>
                {courts.map((court) => (
                  <option key={court.court_id} value={court.court_id}>
                    {court.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Reason</span>
              <input
                maxLength={255}
                onChange={(event) => setForm((current) => ({
                  ...current,
                  reason: event.target.value,
                }))}
                value={form.reason}
              />
            </label>
            <label className="field">
              <span>Starts at</span>
              <input
                onChange={(event) => setForm((current) => ({
                  ...current,
                  starts_at: event.target.value,
                }))}
                required
                type="datetime-local"
                value={form.starts_at}
              />
            </label>
            <label className="field">
              <span>Ends at</span>
              <input
                onChange={(event) => setForm((current) => ({
                  ...current,
                  ends_at: event.target.value,
                }))}
                required
                type="datetime-local"
                value={form.ends_at}
              />
            </label>
          </div>
          <button className="button button-primary" type="submit">Create block-out</button>
        </form>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <span className="step-number">02</span>
          <div>
            <h2>Existing block-outs</h2>
            <p>Active and inactive records are shown.</p>
          </div>
        </div>
        {blockOuts.length === 0 ? (
          <div className="empty-inline">No block-outs found.</div>
        ) : (
          <div className="history-list">
            {blockOuts.map((block) => (
              <article className="history-card" key={block.block_out_id}>
                <div className="history-details">
                  <div><span className="detail-label">Court</span><strong>{block.court_id}</strong></div>
                  <div><span className="detail-label">Starts</span><strong>{block.starts_at}</strong></div>
                  <div><span className="detail-label">Ends</span><strong>{block.ends_at}</strong></div>
                  <div><span className="detail-label">Status</span><strong>{block.is_active ? "ACTIVE" : "INACTIVE"}</strong></div>
                </div>
                {block.is_active && (
                  <div className="history-actions">
                    <button
                      className="button button-danger-outline"
                      onClick={() => void deactivate(block.block_out_id)}
                      type="button"
                    >
                      Deactivate
                    </button>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
