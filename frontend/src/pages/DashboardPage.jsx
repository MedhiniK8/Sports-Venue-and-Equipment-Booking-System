import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { api, AVAILABILITY_CHANGED_EVENT, getApiErrorMessage } from "../api";
import { formatBookingTime, formatVenueDate, getVenueDate } from "../venueTime";

function timeToMinutes(value) {
  const [hours, minutes] = value.slice(0, 5).split(":").map(Number);
  return hours * 60 + minutes;
}

function durationLabel(start, end) {
  const minutes = timeToMinutes(end) - timeToMinutes(start);
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return [hours ? `${hours}h` : "", remainder ? `${remainder}m` : ""].filter(Boolean).join(" ") || "0m";
}

export default function DashboardPage() {
  const location = useLocation();
  const [sports, setSports] = useState([]);
  const [equipmentCatalog, setEquipmentCatalog] = useState([]);
  const [sportId, setSportId] = useState("");
  const [courts, setCourts] = useState([]);
  const [courtId, setCourtId] = useState("");
  const [bookingDate, setBookingDate] = useState("");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [equipmentQuantities, setEquipmentQuantities] = useState({});
  const [availability, setAvailability] = useState(null);
  const [availabilityLoading, setAvailabilityLoading] = useState(false);
  const [availabilityError, setAvailabilityError] = useState("");
  const [referenceDate, setReferenceDate] = useState(getVenueDate());
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [courtError, setCourtError] = useState("");
  const [courtsLoading, setCourtsLoading] = useState(false);
  const [bookingError, setBookingError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [review, setReview] = useState(null);
  const [equipmentDecision, setEquipmentDecision] = useState(null);
  const [confirmedBooking, setConfirmedBooking] = useState(null);
  const [requestCancelled, setRequestCancelled] = useState("");
  const [equipmentAvailability, setEquipmentAvailability] = useState({});

  useEffect(() => {
    let active = true;
    Promise.all([api.getSports(), api.getEquipment()])
      .then(([sportsResponse, equipmentResponse]) => {
        if (!active) return;
        setSports(sportsResponse.data);
        setEquipmentCatalog(equipmentResponse.data);
      })
      .catch((error) => active && setCatalogError(getApiErrorMessage(error.status, error.body)))
      .finally(() => active && setCatalogLoading(false));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const requested = location.state?.sportId || new URLSearchParams(location.search).get("sportId");
    if (requested) setSportId(requested);
  }, [location.search, location.state]);

  useEffect(() => {
    let active = true;
    setCourtId("");
    setCourts([]);
    setAvailability(null);
    setBookingDate("");
    setStartTime("");
    setEndTime("");
    if (!sportId) return () => { active = false; };
    setCourtsLoading(true);
    setCourtError("");
    api.getCourts(sportId)
      .then(({ data }) => active && setCourts(data))
      .catch((error) => active && setCourtError(getApiErrorMessage(error.status, error.body)))
      .finally(() => active && setCourtsLoading(false));
    return () => { active = false; };
  }, [sportId]);

  const refreshAvailability = useCallback(async () => {
    if (!courtId) return;
    setAvailabilityLoading(true);
    setAvailabilityError("");
    try {
      const { data } = await api.getCourtAvailability(courtId, referenceDate);
      setAvailability(data);
    } catch (error) {
      setAvailability(null);
      setAvailabilityError(getApiErrorMessage(error.status, error.body));
    } finally {
      setAvailabilityLoading(false);
    }
  }, [courtId, referenceDate]);

  useEffect(() => { void refreshAvailability(); }, [refreshAvailability]);

  useEffect(() => {
    const refresh = () => void refreshAvailability();
    window.addEventListener(AVAILABILITY_CHANGED_EVENT, refresh);
    return () => window.removeEventListener(AVAILABILITY_CHANGED_EVENT, refresh);
  }, [refreshAvailability]);

  useEffect(() => {
    const selectedIds = Object.keys(equipmentQuantities);
    if (!bookingDate || !startTime || !endTime || selectedIds.length === 0) {
      setEquipmentAvailability({});
      return undefined;
    }
    let active = true;
    Promise.all(selectedIds.map((equipmentId) =>
      api.getEquipmentAvailability(equipmentId, bookingDate, startTime, endTime)
        .then(({ data }) => [equipmentId, data]),
    ))
      .then((entries) => active && setEquipmentAvailability(Object.fromEntries(entries)))
      .catch(() => active && setEquipmentAvailability({}));
    return () => { active = false; };
  }, [bookingDate, startTime, endTime, equipmentQuantities]);

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
      if (checked) next[item.equipment_id] = current[item.equipment_id] || 1;
      else delete next[item.equipment_id];
      return next;
    });
  }

  function buildPayload() {
    return {
      court_id: courtId,
      booking_date: bookingDate,
      start_time: startTime,
      end_time: endTime,
      equipment: requestedEquipment,
    };
  }

  function openReview(event) {
    event.preventDefault();
    setBookingError("");
    setRequestCancelled("");
    setConfirmedBooking(null);
    const payload = buildPayload();
    if (!courtId || !bookingDate || !startTime || !endTime) {
      setBookingError("Select a court, date and time before reviewing the booking.");
      return;
    }
    if (timeToMinutes(endTime) <= timeToMinutes(startTime)) {
      setBookingError("End time must be later than start time.");
      return;
    }
    if (timeToMinutes(startTime) < 360 || timeToMinutes(endTime) > 1200) {
      setBookingError("The booking interval must be within 06:00–20:00.");
      return;
    }
    if (bookingDate < getVenueDate()) {
      setBookingError("A booking cannot be made in the past.");
      return;
    }
    setReview(payload);
  }

  async function sendBooking(payload) {
    setSubmitting(true);
    setBookingError("");
    try {
      const response = await api.createBooking(payload);
      if (response.data?.booking_created === false) {
        setEquipmentDecision(null);
        setReview(null);
        setRequestCancelled("Your request was cancelled.");
        return;
      }
      if (response.status !== 201 || !response.data?.booking_id) {
        throw new Error("The service did not confirm that a booking was created.");
      }
      setReview(null);
      setEquipmentDecision(null);
      setConfirmedBooking(response.data);
      window.dispatchEvent(new Event(AVAILABILITY_CHANGED_EVENT));
    } catch (error) {
      const detail = error.body?.detail ?? error.body;
      if (error.status === 409 && detail?.code === "EQUIPMENT_DECISION_REQUIRED") {
        setReview(null);
        setEquipmentDecision({ payload, shortages: detail.shortages || [] });
      } else if (
        error.status === 503 &&
        detail?.code === "booking_committed_refresh_failed"
      ) {
        setReview(null);
        setConfirmedBooking({
          ...payload,
          booking_id: detail.booking_id,
          status: "BOOKED",
          equipment: payload.equipment,
          cacheWarning: true,
        });
        window.dispatchEvent(new Event(AVAILABILITY_CHANGED_EVENT));
      } else {
        setReview(null);
        setEquipmentDecision(null);
        setBookingError(
          error instanceof Error && !error.status
            ? error.message
            : getApiErrorMessage(error.status, error.body),
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  function selectFreeInterval(day, interval) {
    setBookingDate(day.date);
    setStartTime(formatBookingTime(interval.start_time));
    setEndTime(formatBookingTime(interval.end_time));
  }

  function shiftReference(offset) {
    const date = new Date(`${referenceDate}T12:00:00`);
    date.setDate(date.getDate() + offset);
    setReferenceDate([
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0"),
    ].join("-"));
  }

  return (
    <div className="court-booking-page">
      <section className="booking-page-heading">
        <div>
          <p className="eyebrow">Court booking</p>
          <h1>Make Your Booking Now</h1>
          <p>Choose your sport, select your court and find the perfect time to play.</p>
        </div>
        <button className="button button-quiet" onClick={() => void refreshAvailability()} type="button">Refresh Availability</button>
      </section>

      {catalogError && <div className="notice notice-error" role="alert">{catalogError}</div>}
      {bookingError && <div className="notice notice-error" role="alert">{bookingError}</div>}
      {requestCancelled && <div className="notice notice-info" role="status"><strong>No booking created.</strong> {requestCancelled}</div>}

      {confirmedBooking ? (
        <section className="confirmation-card" aria-labelledby="confirmation-title">
          <div className="confirmation-mark" aria-hidden="true">✓</div>
          <div className="confirmation-content">
            <p className="eyebrow">Booking confirmed</p>
            <h2 id="confirmation-title">You’re all set.</h2>
            {confirmedBooking.cacheWarning && (
              <>
                <div className="notice notice-warning" role="status">Your booking was committed, but availability could not be refreshed.</div>
                <p className="confirmation-id">Booking ID <span>{confirmedBooking.booking_id}</span></p>
              </>
            )}
            <dl className="detail-grid">
              <div><dt>Court</dt><dd>{selectedCourt?.name || "Selected court"}</dd></div>
              <div><dt>Date</dt><dd>{formatVenueDate(confirmedBooking.booking_date)}</dd></div>
              <div><dt>Time · Asia/Kolkata</dt><dd>{formatBookingTime(confirmedBooking.start_time)} – {formatBookingTime(confirmedBooking.end_time)}</dd></div>
              <div><dt>Status</dt><dd><span className="status-pill">{confirmedBooking.status}</span></dd></div>
            </dl>
            {confirmedBooking.equipment?.length > 0 && (
              <div className="confirmed-equipment">
                <h3>Confirmed equipment</h3>
                <ul>
                  {confirmedBooking.equipment.map((item) => (
                    <li key={item.equipment_id}><span>{equipmentNames.get(item.equipment_id) ?? item.equipment_id}</span><strong>× {item.quantity}</strong></li>
                  ))}
                </ul>
              </div>
            )}
            <div className="success-actions">
              <button className="button button-primary" onClick={() => setConfirmedBooking(null)} type="button">Done</button>
            </div>
          </div>
        </section>
      ) : (
        <>
          <section className="panel booking-selection">
            <label className="sr-only">
              <span>Sport</span>
              <select aria-label="Sport" onChange={(event) => setSportId(event.target.value)} value={sportId}>
                <option value="">Select a sport</option>
                {sports.map((sport) => <option key={sport.sport_id} value={sport.sport_id}>{sport.name}</option>)}
              </select>
            </label>
            <div className="sport-selector" aria-label="Sport selection">
              {catalogLoading ? (
                <div className="loading-line" role="status">Loading sports…</div>
              ) : sports.map((sport) => (
                <button
                  aria-pressed={sportId === sport.sport_id}
                  className={`sport-choice${sportId === sport.sport_id ? " is-selected" : ""}`}
                  key={sport.sport_id}
                  onClick={() => setSportId(sport.sport_id)}
                  type="button"
                >
                  {sport.name}
                </button>
              ))}
              {sports.length === 0 && !catalogLoading && <div className="empty-inline">No active sports are listed.</div>}
            </div>

            {sportId && (
              <div className="court-selector" aria-label="Court selection">
                <span>Court</span>
                <label className="sr-only">
                  <span>Court</span>
                  <select aria-label="Court" onChange={(event) => setCourtId(event.target.value)} value={courtId}>
                    <option value="">Select a court</option>
                    {courts.map((court) => <option key={court.court_id} value={court.court_id}>{court.name}</option>)}
                  </select>
                </label>
                {courtsLoading ? (
                  <div className="loading-line" role="status">Loading courts…</div>
                ) : courtError ? (
                  <div className="notice notice-error" role="alert">{courtError}</div>
                ) : courts.map((court) => (
                  <button
                    aria-pressed={courtId === court.court_id}
                    className={`court-choice${courtId === court.court_id ? " is-selected" : ""}`}
                    key={court.court_id}
                    onClick={() => setCourtId(court.court_id)}
                    type="button"
                  >
                    {court.name}
                  </button>
                ))}
              </div>
            )}
          </section>

          {courtId && (
            <section className="panel availability-panel">
              <div className="availability-toolbar">
                <div>
                  <strong>Seven-day availability</strong>
                  <span>Asia/Kolkata · 06:00–20:00</span>
                </div>
                <div className="availability-actions">
                  <button className="button button-quiet" disabled={referenceDate <= getVenueDate()} onClick={() => shiftReference(-7)} type="button">Previous</button>
                  <button className="button button-quiet" onClick={() => setReferenceDate(getVenueDate())} type="button">Today</button>
                  <button className="button button-quiet" onClick={() => shiftReference(7)} type="button">Next</button>
                </div>
              </div>
              <div className="calendar-legend" aria-label="Availability legend">
                <span><i className="legend-free" />Free</span>
                <span><i className="legend-booked" />Booked</span>
                <span><i className="legend-mine" />My Bookings</span>
                <span><i className="legend-blocked" />Admin Blocked</span>
              </div>
              {availabilityLoading ? (
                <div className="loading-line" role="status">Loading availability…</div>
              ) : availabilityError ? (
                <div className="notice notice-error" role="alert">{availabilityError}</div>
              ) : availability ? (
                <div className="availability-calendar">
                  {availability.days.map((day) => (
                    <article className="availability-day" key={day.date}>
                      <button className="availability-date" onClick={() => setBookingDate(day.date)} type="button">
                        <strong>{new Intl.DateTimeFormat("en-IN", { weekday: "short" }).format(new Date(`${day.date}T12:00:00`))}</strong>
                        <span>{formatVenueDate(day.date)}</span>
                      </button>
                      <div className="availability-timeline" aria-label={`Availability for ${day.date}`}>
                        {day.intervals.map((interval, index) => {
                          const left = ((timeToMinutes(interval.start_time) - 360) / 840) * 100;
                          const width = ((timeToMinutes(interval.end_time) - timeToMinutes(interval.start_time)) / 840) * 100;
                          const className = interval.status === "BLOCKED"
                            ? "availability-blocked"
                            : interval.status === "BOOKED"
                              ? interval.is_mine ? "availability-mine" : "availability-booked"
                              : "availability-free";
                          const label = `${interval.status === "BOOKED" && interval.is_mine ? "My booking" : interval.status}: ${formatBookingTime(interval.start_time)} – ${formatBookingTime(interval.end_time)}`;
                          return (
                            <button
                              aria-label={label}
                              className={`availability-segment ${className}`}
                              disabled={interval.status !== "FREE"}
                              key={`${interval.start_time}-${interval.end_time}-${index}`}
                              onClick={() => selectFreeInterval(day, interval)}
                              style={{ left: `${left}%`, width: `${width}%` }}
                              title={label}
                              type="button"
                            >
                              {formatBookingTime(interval.start_time)} – {formatBookingTime(interval.end_time)}
                            </button>
                          );
                        })}
                      </div>
                    </article>
                  ))}
                </div>
              ) : null}
            </section>
          )}

          <form className="booking-details" onSubmit={openReview}>
            <section className="panel">
              <div className="panel-heading">
                <span className="step-number">01</span>
                <div><h2>Booking details</h2><p>Click a free interval or enter a range within venue hours.</p></div>
              </div>
              <div className="field-grid field-grid-three">
                <label className="field">
                  <span>Booking date</span>
                  <input aria-label="Booking date" min={getVenueDate()} onChange={(event) => setBookingDate(event.target.value)} required type="date" value={bookingDate} />
                </label>
                <label className="field">
                  <span>Start time · Asia/Kolkata</span>
                  <input aria-label="Start time · Asia/Kolkata" onChange={(event) => setStartTime(event.target.value)} required step="60" type="time" value={startTime} />
                </label>
                <label className="field">
                  <span>End time · Asia/Kolkata</span>
                  <input aria-label="End time · Asia/Kolkata" onChange={(event) => setEndTime(event.target.value)} required step="60" type="time" value={endTime} />
                </label>
              </div>
            </section>

            <section className="panel equipment-section">
              <div className="panel-heading">
                <span className="step-number">02</span>
                <div><h2>Equipment <span className="optional-label">Optional</span></h2><p>Choose from the active backend equipment catalogue.</p></div>
              </div>
              {equipmentCatalog.length === 0 ? (
                <div className="empty-inline">No active equipment types are listed.</div>
              ) : (
                <div className="equipment-grid">
                  {equipmentCatalog.map((item) => {
                    const selected = Object.hasOwn(equipmentQuantities, item.equipment_id);
                    return (
                      <article className={`equipment-card${selected ? " is-selected" : ""}`} key={item.equipment_id}>
                        <label className="equipment-select">
                          <input checked={selected} onChange={(event) => changeEquipmentSelection(item, event.target.checked)} type="checkbox" />
                          <span>{item.name}</span>
                        </label>
                        {selected && (
                          <>
                            {equipmentAvailability[item.equipment_id] && (
                              <p className="field-hint">Remaining for interval: {equipmentAvailability[item.equipment_id].remaining_quantity}</p>
                            )}
                            <label className="quantity-field">
                              <span>Quantity</span>
                              <input aria-label={`Quantity for ${item.name}`} min="1" onChange={(event) => setEquipmentQuantities((current) => ({ ...current, [item.equipment_id]: Number(event.target.value) }))} required type="number" value={equipmentQuantities[item.equipment_id]} />
                            </label>
                          </>
                        )}
                      </article>
                    );
                  })}
                </div>
              )}
              <button className="button button-primary booking-submit" disabled={submitting || !courtId || !bookingDate || !startTime || !endTime} type="submit">
                {submitting ? "Checking request…" : "Submit booking request"}
              </button>
            </section>
          </form>
        </>
      )}

      {review && (
        <div className="dialog-backdrop" role="presentation">
          <section aria-labelledby="booking-review-title" aria-modal="true" className="decision-dialog" role="dialog">
            <p className="eyebrow">Review request</p>
            <h2 id="booking-review-title">Review your booking</h2>
            <dl className="confirmation-summary">
              <div><dt>Sport</dt><dd>{selectedSport?.name}</dd></div>
              <div><dt>Court</dt><dd>{selectedCourt?.name}</dd></div>
              <div><dt>Date</dt><dd>{formatVenueDate(review.booking_date)}</dd></div>
              <div><dt>Time</dt><dd>{review.start_time} – {review.end_time}</dd></div>
              <div><dt>Duration</dt><dd>{durationLabel(review.start_time, review.end_time)}</dd></div>
              <div><dt>Equipment</dt><dd>{review.equipment.length ? review.equipment.map((item) => `${equipmentNames.get(item.equipment_id) ?? item.equipment_id} × ${item.quantity}`).join(", ") : "No equipment required"}</dd></div>
            </dl>
            <div className="decision-actions">
              <button className="button button-quiet" disabled={submitting} onClick={() => setReview(null)} type="button">Back</button>
              <button className="button button-primary" disabled={submitting} onClick={() => void sendBooking(review)} type="button">{submitting ? "Submitting…" : "Confirm Booking"}</button>
            </div>
          </section>
        </div>
      )}

      {equipmentDecision && (
        <div className="dialog-backdrop" role="presentation">
          <section aria-labelledby="equipment-decision-title" aria-modal="true" className="decision-dialog" role="dialog">
            <p className="eyebrow">Your choice is needed</p>
            <h2 id="equipment-decision-title">Some equipment isn’t available</h2>
            <ul className="shortage-list">
              {equipmentDecision.shortages.map((shortage) => (
                <li key={shortage.equipment_id}>
                  <div><strong>{equipmentNames.get(shortage.equipment_id) ?? shortage.equipment_id}</strong><span>Requested {shortage.requested_quantity}</span></div>
                  <span className="available-quantity">{shortage.available_quantity} available</span>
                </li>
              ))}
            </ul>
            <div className="decision-actions">
              <button className="button button-primary" disabled={submitting} onClick={() => void sendBooking({ ...equipmentDecision.payload, equipment_decision: "CONTINUE_WITHOUT_EQUIPMENT" })} type="button">Continue without unavailable equipment</button>
              <button className="button button-quiet" disabled={submitting} onClick={() => { setEquipmentDecision(null); setRequestCancelled("Your request was cancelled."); }} type="button">Cancel request</button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
