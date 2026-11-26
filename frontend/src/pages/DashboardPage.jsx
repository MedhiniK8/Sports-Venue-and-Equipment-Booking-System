import React, { useEffect, useMemo, useState } from "react";
import { api, getApiErrorMessage } from "../api";
import { formatBookingTime, formatVenueDate, getVenueDate } from "../venueTime";

function BookingConfirmation({ booking, courtName, equipment }) {
  return (
    <section className="confirmation-card" aria-labelledby="confirmation-title">
      <div className="confirmation-mark" aria-hidden="true">✓</div>
      <div className="confirmation-content">
        <p className="eyebrow">Booking confirmed</p>
        <h2 id="confirmation-title">You’re all set.</h2>
        <p className="confirmation-id">
          Booking ID <span>{booking.booking_id}</span>
        </p>
        {booking.cacheWarning && (
          <div className="notice notice-warning" role="status">
            Your booking was committed. The availability display may be stale
            because it could not be refreshed. Equipment allocation details
            will be available in booking history.
          </div>
        )}
        <dl className="detail-grid">
          <div><dt>Court</dt><dd>{courtName}</dd></div>
          <div><dt>Date</dt><dd>{formatVenueDate(booking.booking_date)}</dd></div>
          <div>
            <dt>Time · Asia/Kolkata</dt>
            <dd>{formatBookingTime(booking.start_time)} – {formatBookingTime(booking.end_time)}</dd>
          </div>
          <div><dt>Status</dt><dd><span className="status-pill">{booking.status}</span></dd></div>
        </dl>
        {booking.equipment && booking.equipment.length > 0 && (
          <div className="confirmed-equipment">
            <h3>Confirmed equipment</h3>
            <ul>
              {booking.equipment.map((item) => (
                <li key={item.equipment_id}>
                  <span>{equipment.get(item.equipment_id) ?? item.equipment_id}</span>
                  <strong>× {item.quantity}</strong>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}

export default function DashboardPage() {
  const [sports, setSports] = useState([]);
  const [equipmentCatalog, setEquipmentCatalog] = useState([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [sportId, setSportId] = useState("");
  const [courts, setCourts] = useState([]);
  const [courtsLoading, setCourtsLoading] = useState(false);
  const [courtError, setCourtError] = useState("");
  const [courtId, setCourtId] = useState("");
  const [bookingDate, setBookingDate] = useState("");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [equipmentQuantities, setEquipmentQuantities] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [bookingError, setBookingError] = useState("");
  const [decision, setDecision] = useState(null);
  const [requestCancelled, setRequestCancelled] = useState("");
  const [confirmedBooking, setConfirmedBooking] = useState(null);

  useEffect(() => {
    let active = true;
    async function loadCatalog() {
      setCatalogLoading(true);
      setCatalogError("");
      try {
        const [sportsResponse, equipmentResponse] = await Promise.all([
          api.getSports(),
          api.getEquipment(),
        ]);
        if (active) {
          setSports(sportsResponse.data);
          setEquipmentCatalog(equipmentResponse.data);
        }
      } catch (error) {
        if (active) {
          setCatalogError(getApiErrorMessage(error.status, error.body));
        }
      } finally {
        if (active) {
          setCatalogLoading(false);
        }
      }
    }
    loadCatalog();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    if (!sportId) {
      setCourts([]);
      setCourtId("");
      setCourtError("");
      setCourtsLoading(false);
      return () => {
        active = false;
      };
    }

    setCourts([]);
    setCourtId("");
    setCourtError("");
    setCourtsLoading(true);
    api
      .getCourts(sportId)
      .then(({ data }) => {
        if (active) {
          setCourts(data);
        }
      })
      .catch((error) => {
        if (active) {
          setCourtError(getApiErrorMessage(error.status, error.body));
        }
      })
      .finally(() => {
        if (active) {
          setCourtsLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [sportId]);

  const selectedSport = sports.find((sport) => sport.sport_id === sportId);
  const selectedCourt = courts.find((court) => court.court_id === courtId);
  const equipmentNames = useMemo(
    () => new Map(equipmentCatalog.map((item) => [item.equipment_id, item.name])),
    [equipmentCatalog],
  );
  const requestedEquipment = equipmentCatalog
    .filter((item) => Object.hasOwn(equipmentQuantities, item.equipment_id))
    .map((item) => ({
      equipment_id: item.equipment_id,
      quantity: equipmentQuantities[item.equipment_id],
    }));

  function changeEquipmentSelection(item, checked) {
    setEquipmentQuantities((current) => {
      const next = { ...current };
      if (checked) {
        next[item.equipment_id] = current[item.equipment_id] || 1;
      } else {
        delete next[item.equipment_id];
      }
      return next;
    });
  }

  function buildRequest() {
    return {
      court_id: courtId,
      booking_date: bookingDate,
      start_time: startTime,
      end_time: endTime,
      equipment: requestedEquipment,
    };
  }

  async function sendBooking(payload) {
    setSubmitting(true);
    setBookingError("");
    setRequestCancelled("");
    try {
      const response = await api.createBooking(payload);
      if (response.data?.booking_created === false) {
        setDecision(null);
        setRequestCancelled("Your request was cancelled.");
        return;
      }
      if (response.status !== 201 || !response.data?.booking_id) {
        throw new Error("The service did not confirm that a booking was created.");
      }
      setDecision(null);
      setConfirmedBooking(response.data);
    } catch (error) {
      const detail = error.body?.detail;
      if (
        error.status === 503 &&
        detail?.code === "booking_committed_refresh_failed" &&
        detail.committed === true &&
        detail.booking_id
      ) {
        setDecision(null);
        setConfirmedBooking({
          booking_id: detail.booking_id,
          court_id: payload.court_id,
          booking_date: payload.booking_date,
          start_time: payload.start_time,
          end_time: payload.end_time,
          status: "BOOKED",
          equipment: null,
          cacheWarning: true,
        });
        return;
      }
      if (error.status === 409 && error.body?.code === "EQUIPMENT_DECISION_REQUIRED") {
        setDecision({ payload, shortages: error.body.shortages || [] });
        return;
      }
      setBookingError(
        error instanceof Error && !(error.status || error.status === 0)
          ? error.message
          : getApiErrorMessage(error.status, error.body),
      );
    } finally {
      setSubmitting(false);
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    setConfirmedBooking(null);
    setRequestCancelled("");
    setBookingError("");
    void sendBooking(buildRequest());
  }

  function continueWithoutUnavailableEquipment() {
    if (!decision) return;
    const requestWithDecision = {
      ...decision.payload,
      equipment_decision: "CONTINUE_WITHOUT_EQUIPMENT",
    };
    setDecision(null);
    void sendBooking(requestWithDecision);
  }

  function cancelRequest() {
    setDecision(null);
    setRequestCancelled("Your request was cancelled.");
    setConfirmedBooking(null);
  }

  function startAnotherBooking() {
    setConfirmedBooking(null);
    setRequestCancelled("");
    setBookingError("");
    setSportId("");
    setCourtId("");
    setBookingDate("");
    setStartTime("");
    setEndTime("");
    setEquipmentQuantities({});
  }

  return (
    <div className="dashboard-page">
      <section className="page-hero">
        <div>
          <p className="eyebrow">Student booking</p>
          <h1>Find your court time.</h1>
          <p>Choose a sport, build your request, and let the venue confirm availability.</p>
        </div>
        <div className="hero-aside">
          <span className="hero-icon" aria-hidden="true">◉</span>
          <span>Venue time<br /><strong>Asia/Kolkata</strong></span>
        </div>
      </section>

      {catalogError && <div className="notice notice-error" role="alert">{catalogError}</div>}
      {bookingError && <div className="notice notice-error" role="alert">{bookingError}</div>}
      {requestCancelled && (
        <div className="notice notice-info" role="status">
          <strong>No booking created.</strong> {requestCancelled}
        </div>
      )}

      {confirmedBooking && (
        <BookingConfirmation
          booking={confirmedBooking}
          courtName={courts.find((court) => court.court_id === confirmedBooking.court_id)?.name ?? selectedCourt?.name ?? "Selected court"}
          equipment={equipmentNames}
        />
      )}

      {!confirmedBooking && (
        <form className="booking-layout" onSubmit={handleSubmit}>
          <div className="booking-main">
            <section className="panel">
              <div className="panel-heading">
                <span className="step-number">01</span>
                <div>
                  <h2>Choose your court</h2>
                  <p>Sports and courts are loaded from the venue catalog.</p>
                </div>
              </div>
              {catalogLoading ? (
                <div className="loading-line" role="status">Loading sports and equipment…</div>
              ) : sports.length === 0 ? (
                <div className="empty-inline">No active sports are listed right now.</div>
              ) : (
                <div className="field-grid">
                  <label className="field">
                    <span>Sport</span>
                    <select
                      onChange={(event) => setSportId(event.target.value)}
                      required
                      value={sportId}
                    >
                      <option value="">Select a sport</option>
                      {sports.map((sport) => (
                        <option key={sport.sport_id} value={sport.sport_id}>{sport.name}</option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Court</span>
                    <select
                      disabled={!sportId || courtsLoading || courts.length === 0}
                      onChange={(event) => setCourtId(event.target.value)}
                      required
                      value={courtId}
                    >
                      <option value="">
                        {courtsLoading ? "Loading courts…" : sportId ? "Select a court" : "Choose a sport first"}
                      </option>
                      {courts.map((court) => (
                        <option key={court.court_id} value={court.court_id}>{court.name}</option>
                      ))}
                    </select>
                  </label>
                  {courtError && <p className="field-error" role="alert">{courtError}</p>}
                  {sportId && !courtsLoading && !courtError && courts.length === 0 && (
                    <p className="field-hint">No active courts are listed for this sport.</p>
                  )}
                </div>
              )}
            </section>

            <section className="panel">
              <div className="panel-heading">
                <span className="step-number">02</span>
                <div>
                  <h2>Choose date and time</h2>
                  <p>Times are entered as venue-local time. Availability is checked when you submit.</p>
                </div>
              </div>
              <div className="field-grid field-grid-three">
                <label className="field">
                  <span>Booking date</span>
                  <input
                    min={getVenueDate()}
                    onChange={(event) => setBookingDate(event.target.value)}
                    required
                    type="date"
                    value={bookingDate}
                  />
                </label>
                <label className="field">
                  <span>Start time · Asia/Kolkata</span>
                  <input
                    onChange={(event) => setStartTime(event.target.value)}
                    required
                    step="60"
                    type="time"
                    value={startTime}
                  />
                </label>
                <label className="field">
                  <span>End time · Asia/Kolkata</span>
                  <input
                    onChange={(event) => setEndTime(event.target.value)}
                    required
                    step="60"
                    type="time"
                    value={endTime}
                  />
                </label>
              </div>
              <p className="field-hint">
                Enter an interval in HH:MM. Court operating hours and availability
                are validated by the booking service; no unconfirmed time is shown as available.
              </p>
            </section>

            <section className="panel">
              <div className="panel-heading">
                <span className="step-number">03</span>
                <div>
                  <h2>Equipment <span className="optional-label">Optional</span></h2>
                  <p>Choose equipment types and requested quantities.</p>
                </div>
              </div>
              {catalogLoading ? (
                <div className="loading-line" role="status">Loading equipment…</div>
              ) : equipmentCatalog.length === 0 ? (
                <div className="empty-inline">No active equipment types are listed.</div>
              ) : (
                <div className="equipment-grid">
                  {equipmentCatalog.map((item) => {
                    const selected = Object.hasOwn(equipmentQuantities, item.equipment_id);
                    return (
                      <article className={`equipment-card${selected ? " is-selected" : ""}`} key={item.equipment_id}>
                        <label className="equipment-select">
                          <input
                            checked={selected}
                            onChange={(event) => changeEquipmentSelection(item, event.target.checked)}
                            type="checkbox"
                          />
                          <span className="equipment-symbol" aria-hidden="true">＋</span>
                          <span>{item.name}</span>
                        </label>
                        {selected && (
                          <label className="quantity-field">
                            <span>Quantity</span>
                            <input
                              aria-label={`Quantity for ${item.name}`}
                              min="1"
                              onChange={(event) => {
                                const value = Number(event.target.value);
                                setEquipmentQuantities((current) => ({
                                  ...current,
                                  [item.equipment_id]: value,
                                }));
                              }}
                              required
                              type="number"
                              value={equipmentQuantities[item.equipment_id]}
                            />
                          </label>
                        )}
                      </article>
                    );
                  })}
                </div>
              )}
            </section>
          </div>

          <aside className="booking-sidebar">
            <section className="review-card">
              <div className="review-heading">
                <span className="review-icon" aria-hidden="true">▤</span>
                <div>
                  <p className="eyebrow">Review request</p>
                  <h2>Session summary</h2>
                </div>
              </div>
              <dl className="review-list">
                <div><dt>Sport</dt><dd>{selectedSport?.name || "Not selected"}</dd></div>
                <div><dt>Court</dt><dd>{selectedCourt?.name || "Not selected"}</dd></div>
                <div><dt>Date</dt><dd>{bookingDate ? formatVenueDate(bookingDate) : "Not selected"}</dd></div>
                <div>
                  <dt>Time · Asia/Kolkata</dt>
                  <dd>{startTime && endTime ? `${startTime} – ${endTime}` : "Not selected"}</dd>
                </div>
                <div>
                  <dt>Equipment requested</dt>
                  <dd>
                    {requestedEquipment.length
                      ? requestedEquipment.map((item) =>
                        `${equipmentNames.get(item.equipment_id)} × ${item.quantity}`,
                      ).join(", ")
                      : "None"}
                  </dd>
                </div>
              </dl>
              <button
                className="button button-primary button-wide"
                disabled={
                  submitting ||
                  catalogLoading ||
                  !courtId ||
                  !bookingDate ||
                  !startTime ||
                  !endTime ||
                  requestedEquipment.some((item) => !Number.isInteger(item.quantity) || item.quantity < 1)
                }
                type="submit"
              >
                {submitting ? "Checking request…" : "Submit booking request"}
              </button>
              <p className="review-footnote">
                Your booking is confirmed only after the backend accepts it.
              </p>
            </section>
          </aside>
        </form>
      )}

      {confirmedBooking && (
        <button className="button button-secondary start-another" onClick={startAnotherBooking} type="button">
          Make another booking
        </button>
      )}

      {decision && (
        <div className="dialog-backdrop">
          <section
            aria-labelledby="equipment-decision-title"
            aria-modal="true"
            className="decision-dialog"
            role="dialog"
          >
            <div className="dialog-mark" aria-hidden="true">!</div>
            <p className="eyebrow">Your choice is needed</p>
            <h2 id="equipment-decision-title">Some equipment isn’t available</h2>
            <p className="dialog-copy">
              Review every shortage and choose whether to continue without unavailable equipment or cancel this request.
            </p>
            <ul className="shortage-list">
              {decision.shortages.map((shortage) => (
                <li key={shortage.equipment_id}>
                  <div>
                    <strong>{equipmentNames.get(shortage.equipment_id) ?? shortage.equipment_id}</strong>
                    <span>Requested {shortage.requested_quantity}</span>
                  </div>
                  <span className="available-quantity">{shortage.available_quantity} available</span>
                </li>
              ))}
            </ul>
            <div className="decision-actions">
              <button
                className="button button-primary"
                disabled={submitting}
                onClick={continueWithoutUnavailableEquipment}
                type="button"
              >
                Continue without unavailable equipment
              </button>
              <button
                className="button button-quiet"
                disabled={submitting}
                onClick={cancelRequest}
                type="button"
              >
                Cancel request
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
