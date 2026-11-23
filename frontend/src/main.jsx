import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import "./styles.css";

const cards = [
  {
    title: "Sports",
    description: "Browse available sports and disciplines.",
  },
  {
    title: "Courts",
    description: "View venue courts and operating information.",
  },
  {
    title: "My Bookings",
    description: "Review and manage your reservations.",
  },
];

function App() {
  const [backendStatus, setBackendStatus] = useState("checking");

  useEffect(() => {
    fetch("/api/health")
      .then((response) => {
        if (!response.ok) throw new Error("Health check failed");
        return response.json();
      })
      .then((data) => setBackendStatus(data.status === "ok" ? "online" : "offline"))
      .catch(() => setBackendStatus("offline"));
  }, []);

  return (
    <div className="app-shell">
      <header className="header">
        <div>
          <p className="eyebrow">Campus facilities</p>
          <h1>Sports Venue Booking</h1>
        </div>
        <div className={`status status-${backendStatus}`} aria-live="polite">
          <span className="status-dot" />
          Backend {backendStatus}
        </div>
      </header>

      <main>
        <section className="welcome" aria-labelledby="dashboard-title">
          <div>
            <p className="eyebrow">Dashboard</p>
            <h2 id="dashboard-title">Plan your next session</h2>
          </div>
          <span className="coming-soon">Bookings Coming Soon</span>
        </section>

        <section className="card-grid" aria-label="Dashboard sections">
          {cards.map((card) => (
            <article className="card" key={card.title}>
              <div className="card-heading">
                <h3>{card.title}</h3>
                <span>Coming Soon</span>
              </div>
              <p>{card.description}</p>
            </article>
          ))}
        </section>
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
