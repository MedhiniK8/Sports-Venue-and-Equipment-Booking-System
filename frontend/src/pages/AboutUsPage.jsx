import React from "react";

export default function AboutUsPage() {
  return (
    <div className="dashboard-page">
      <section className="page-hero">
        <div>
          <p className="eyebrow">About the project</p>
          <h1>Campus Play</h1>
          <p>A sports venue and equipment booking platform for students.</p>
        </div>
      </section>
      <section className="content-section general-info about-grid">
        <article>
          <p className="eyebrow">Introduction</p>
          <h2>Purpose</h2>
          <p>Campus Play helps registered students discover sports, choose court intervals and manage their bookings.</p>
        </article>
        <article>
          <p className="eyebrow">Features</p>
          <h2>Main features</h2>
          <ul>
            <li>Student registration and login</li>
            <li>Sports, court and equipment catalogues</li>
            <li>Booking creation and history</li>
            <li>Eligible booking cancellation</li>
          </ul>
        </article>
        <article>
          <p className="eyebrow">Team</p>
          <h2>Project team</h2>
          <p>Team information can be updated here when the official names and roles are provided.</p>
        </article>
      </section>
    </div>
  );
}
