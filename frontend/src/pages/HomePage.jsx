import React, { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, getApiErrorMessage } from "../api";

const SPORT_PRESENTATION = {
  Basketball: { description: "Take your game to the court and make every shot count.", image: "/images/sports/basketball.jpg" },
  Badminton: { description: "Bring your speed, precision and competitive spirit.", image: "/images/sports/badminton.jpg" },
  "Table Tennis": { description: "Fast rallies, sharp reflexes and endless excitement.", image: "/images/sports/table-tennis.jpg" },
  Squash: { description: "Challenge your agility and push your limits.", image: "/images/sports/squash.jpg" },
  Volleyball: { description: "Teamwork, energy and action in every rally.", image: "/images/sports/volleyball.jpg" },
  Kabaddi: { description: "Strength, strategy and teamwork come together.", image: "/images/sports/kabaddi.jpg" },
};

export default function HomePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const exploreRef = useRef(null);
  const [sports, setSports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api.getSports()
      .then(({ data }) => active && setSports(data))
      .catch((requestError) => active && setError(getApiErrorMessage(requestError.status, requestError.body)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (location.state?.scrollToExplore) {
      window.requestAnimationFrame(() => {
        exploreRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }, [location.state]);

  function scrollToExplore() {
    exploreRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function bookSport(sportId) {
    navigate("/court-booking", { state: { sportId } });
  }

  const approvedOrder = ["Basketball", "Badminton", "Table Tennis", "Squash", "Volleyball", "Kabaddi"];
  const orderedSports = approvedOrder
    .map((name) => sports.find((sport) => sport.name === name))
    .filter(Boolean);

  return (
    <div className="home-page">
      <header className="home-header">
        <span className="home-header-label">SportsHub / University Sports Booking</span>
        <span className="home-header-time">Asia/Kolkata</span>
      </header>

      <section className="home-hero">
        <div className="home-hero-overlay" />
        <div className="home-hero-content">
          <p className="eyebrow">University Sports Booking</p>
          <h1 aria-label="Your Game. Your Court. Your Time.">Your Game. Your Court. <strong>Your Time.</strong></h1>
          <p>Book sports courts and optional equipment for every session.</p>
          <div className="hero-actions">
            <button className="button button-primary" onClick={scrollToExplore} type="button">Explore</button>
            <button className="button button-hero-outline" onClick={() => navigate("/court-booking")} type="button">Book Court Now</button>
          </div>
        </div>
      </section>

      <section className="explore-section" id="explore" ref={exploreRef}>
        <div className="explore-heading">
          <p className="eyebrow">Discover campus sports</p>
          <h2>Explore Our Sports</h2>
          <p>Find a sport, choose a court and reserve your time.</p>
        </div>

        {loading ? (
          <div className="loading-panel" role="status">Loading sports…</div>
        ) : error ? (
          <div className="notice notice-error" role="alert">{error}</div>
        ) : orderedSports.length === 0 ? (
          <div className="empty-state">
            <h2>No active approved sports</h2>
            <p>The live catalogue does not currently list an approved sport.</p>
          </div>
        ) : (
          <div className="sports-banners">
            {Array.from({ length: Math.ceil(orderedSports.length / 2) }, (_, index) => (
              orderedSports.slice(index * 2, index * 2 + 2)
            )).map((pair, index) => (
              <div className="sports-showcase" key={index}>
                {pair.map((sport, pairIndex) => {
                  const presentation = SPORT_PRESENTATION[sport.name];
                  return (
                    <article
                      className={`sports-showcase-half showcase-${pairIndex % 2 === 0 ? "left" : "right"}`}
                      key={sport.sport_id}
                      style={{ "--sport-image": `url("${presentation.image}")` }}
                    >
                      <div className="showcase-overlay" />
                      <div className="showcase-copy">
                        <h3>{sport.name}</h3>
                        <p>{presentation.description}</p>
                        <button className="button button-primary" onClick={() => bookSport(sport.sport_id)} type="button">Book Now</button>
                      </div>
                    </article>
                  );
                })}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
