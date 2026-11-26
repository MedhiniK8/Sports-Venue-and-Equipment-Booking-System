import React, { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, getApiErrorMessage } from "../api";

export default function ExplorePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [sports, setSports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const highlightedSportId = location.state?.sportId;

  useEffect(() => {
    let active = true;
    api.getSports()
      .then(({ data }) => {
        if (active) setSports(data);
      })
      .catch((requestError) => {
        if (active) setError(getApiErrorMessage(requestError.status, requestError.body));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  function bookSport(sportId) {
    navigate("/court-booking", { state: { sportId } });
  }

  return (
    <div className="dashboard-page">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Discover</p>
          <h1>Explore sports</h1>
          <p>Choose a sport and continue to its court catalogue.</p>
        </div>
      </section>

      {loading ? (
        <div className="loading-panel" role="status">Loading sports…</div>
      ) : error ? (
        <div className="notice notice-error" role="alert">{error}</div>
      ) : sports.length === 0 ? (
        <div className="empty-state">
          <h2>No sports available</h2>
          <p>There are no active sports in the catalogue.</p>
        </div>
      ) : (
        <div className="sport-grid">
          {sports.map((sport) => (
            <article
              className={`sport-card${sport.sport_id === highlightedSportId ? " is-highlighted" : ""}`}
              key={sport.sport_id}
            >
              <div className="sport-placeholder" aria-hidden="true">
                {sport.name.slice(0, 1).toUpperCase()}
              </div>
              <div>
                <h3>{sport.name}</h3>
                <p>Browse the active courts available for this sport.</p>
              </div>
              <button
                className="button button-primary"
                onClick={() => bookSport(sport.sport_id)}
                type="button"
              >
                Book This Sport
              </button>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
