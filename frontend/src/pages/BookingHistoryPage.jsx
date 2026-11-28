import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  AVAILABILITY_CHANGED_EVENT,
  getApiErrorMessage,
} from "../api";
import { isBookingCancelable, formatBookingTime, formatVenueDate } from "../venueTime";

function EquipmentList({ items, equipmentNames }) {
  if (!items.length) {
    return <span className="muted-copy">No equipment</span>;
  }
  return (
    <ul className="history-equipment">
      {items.map((item) => (
        <li key={item.equipment_id}>
          {equipmentNames.get(item.equipment_id) ?? item.equipment_id}
          <strong>× {item.quantity}</strong>
        </li>
      ))}
    </ul>
  );
}

export default function BookingHistoryPage() {
  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [lookupError, setLookupError] = useState("");
  const [courtNames, setCourtNames] = useState(new Map());
  const [equipmentNames, setEquipmentNames] = useState(new Map());
  const [notice, setNotice] = useState("");
  const [actionError, setActionError] = useState("");
  const [cancellingId, setCancellingId] = useState("");
  const [pendingCancellation, setPendingCancellation] = useState(null);
  const [activeTab, setActiveTab] = useState("upcoming");

  const refreshBookings = useCallback(async () => {
    setLoading(true);
    setHistoryError("");
    try {
      const { data } = await api.getBookings();
      setBookings(data);
    } catch (error) {
      setHistoryError(getApiErrorMessage(error.status, error.body));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshBookings();
  }, [refreshBookings]);

  useEffect(() => {
    let active = true;
    async function loadCatalogNames() {
      setLookupError("");
      try {
        const [sportsResponse, equipmentResponse] = await Promise.all([
          api.getSports(),
          api.getEquipment(),
        ]);
        const courtResponses = await Promise.all(
          sportsResponse.data.map((sport) => api.getCourts(sport.sport_id)),
        );
        if (active) {
          setCourtNames(
            new Map(
              courtResponses.flatMap((response) =>
                response.data.map((court) => [court.court_id, court.name]),
              ),
            ),
          );
          setEquipmentNames(
            new Map(
              equipmentResponse.data.map((item) => [item.equipment_id, item.name]),
            ),
          );
        }
      } catch (error) {
        if (active) {
          setLookupError(
            `Some catalog names could not be loaded. Booking IDs are shown where names are unavailable. ${getApiErrorMessage(error.status, error.body)}`,
          );
        }
      }
    }
    void loadCatalogNames();
    return () => {
      active = false;
    };
  }, []);

  const sortedBookings = useMemo(
    () => [...bookings].sort((a, b) => {
      const aStart = `${a.booking_date}T${a.start_time}`;
      const bStart = `${b.booking_date}T${b.start_time}`;
      return bStart.localeCompare(aStart);
    }),
    [bookings],
  );

  async function handleCancel(booking) {
    setCancellingId(booking.booking_id);
    setActionError("");
    setNotice("");
    try {
      const response = await api.cancelBooking(booking.booking_id);
      if (response.data?.status !== "CANCELLED") {
        throw new Error("The service did not confirm the cancellation.");
      }
      setBookings((current) =>
        current.map((item) =>
          item.booking_id === booking.booking_id ? response.data : item,
        ),
      );
      setNotice(`Booking ${booking.booking_id} was cancelled.`);
      window.dispatchEvent(new Event(AVAILABILITY_CHANGED_EVENT));
    } catch (error) {
      const detail = error.body?.detail;
      if (
        error.status === 503 &&
        detail?.code === "cancellation_committed_refresh_failed" &&
        detail.committed === true
      ) {
        setBookings((current) =>
          current.map((item) =>
            item.booking_id === booking.booking_id
              ? { ...item, status: "CANCELLED" }
              : item,
          ),
        );
        setNotice(
          `Booking ${booking.booking_id} was cancelled. Availability may need refreshing.`,
        );
        window.dispatchEvent(new Event(AVAILABILITY_CHANGED_EVENT));
      } else {
        setActionError(getApiErrorMessage(error.status, error.body));
      }
    } finally {
      setCancellingId("");
      setPendingCancellation(null);
    }
  }

  const nowDate = new Date().toISOString().slice(0, 10);
  const visibleBookings = sortedBookings.filter((booking) => {
    if (activeTab === "cancelled") return booking.status === "CANCELLED";
    if (activeTab === "past") {
      return booking.status !== "CANCELLED" &&
        `${booking.booking_date}T${booking.end_time}` < nowDate;
    }
    return booking.status === "BOOKED" &&
      `${booking.booking_date}T${booking.end_time}` >= nowDate;
  });

  return (
    <section className="history-page">
      <div className="page-hero history-hero">
        <div>
          <p className="eyebrow">Your activity</p>
          <h1>My bookings</h1>
          <p>Review your reservations and manage eligible bookings.</p>
        </div>
        <Link className="button button-primary" to="/court-booking">Book a court</Link>
      </div>

      {notice && <div className="notice notice-success" role="status">{notice}</div>}
      {actionError && <div className="notice notice-error" role="alert">{actionError}</div>}
      {lookupError && <div className="notice notice-warning" role="status">{lookupError}</div>}
      {historyError && <div className="notice notice-error" role="alert">{historyError}</div>}

      {loading ? (
        <div className="loading-panel" role="status">
          <span className="spinner" aria-hidden="true" />
          Loading your bookings…
        </div>
      ) : historyError ? null : sortedBookings.length === 0 ? (
        <div className="empty-state">
          <span className="empty-icon" aria-hidden="true">▤</span>
          <h2>No bookings yet</h2>
          <p>Your confirmed reservations will appear here.</p>
          <Link className="button button-primary" to="/court-booking">Explore sports</Link>
        </div>
      ) : (
        <>
          <div className="history-tabs" aria-label="Booking categories">
            <button className={activeTab === "upcoming" ? "is-active" : ""} onClick={() => setActiveTab("upcoming")} type="button">Upcoming / Current</button>
            <button className={activeTab === "past" ? "is-active" : ""} onClick={() => setActiveTab("past")} type="button">Past</button>
            <button className={activeTab === "cancelled" ? "is-active" : ""} onClick={() => setActiveTab("cancelled")} type="button">Cancelled</button>
          </div>
          {visibleBookings.length === 0 ? (
            <div className="empty-state"><h2>No bookings in this category</h2><p>Choose another tab or create a new reservation.</p></div>
          ) : (
        <div className="history-list">
          {visibleBookings.map((booking) => {
            const cancelable = isBookingCancelable(booking);
            return (
              <article className="history-card" key={booking.booking_id}>
                <div className="history-card-top">
                  <div>
                    <p className="eyebrow">Booking ID</p>
                    <p className="booking-id">{booking.booking_id}</p>
                  </div>
                  <span className={`status-pill status-${booking.status.toLowerCase()}`}>
                    {booking.status}
                  </span>
                </div>
                <div className="history-details">
                  <div>
                    <span className="detail-label">Court</span>
                    <strong>{courtNames.get(booking.court_id) ?? `Court ${booking.court_id}`}</strong>
                  </div>
                  <div>
                    <span className="detail-label">Date</span>
                    <strong>{formatVenueDate(booking.booking_date)}</strong>
                  </div>
                  <div>
                    <span className="detail-label">Time · Asia/Kolkata</span>
                    <strong>{formatBookingTime(booking.start_time)} – {formatBookingTime(booking.end_time)}</strong>
                  </div>
                  <div>
                    <span className="detail-label">Equipment</span>
                    <EquipmentList items={booking.equipment} equipmentNames={equipmentNames} />
                  </div>
                </div>
                {cancelable && (
                  <div className="history-actions">
                    <button
                      className="button button-danger-outline"
                      disabled={cancellingId === booking.booking_id}
                      onClick={() => setPendingCancellation(booking)}
                      type="button"
                    >
                      {cancellingId === booking.booking_id ? "Cancelling…" : "Cancel booking"}
                    </button>
                  </div>
                )}
              </article>
            );
          })}
        </div>
          )}
        </>
      )}
      {pendingCancellation && (
        <div className="dialog-backdrop" role="presentation">
          <section aria-labelledby="cancel-title" aria-modal="true" className="decision-dialog" role="dialog">
            <p className="eyebrow">Confirm cancellation</p>
            <h2 id="cancel-title">Cancel this booking?</h2>
            <p className="dialog-copy">
              {courtNames.get(pendingCancellation.court_id) ?? "This court"} · {formatVenueDate(pendingCancellation.booking_date)} · {formatBookingTime(pendingCancellation.start_time)}–{formatBookingTime(pendingCancellation.end_time)}
            </p>
            <div className="decision-actions">
              <button className="button button-danger-outline" disabled={cancellingId === pendingCancellation.booking_id} onClick={() => void handleCancel(pendingCancellation)} type="button">Cancel Booking</button>
              <button className="button button-quiet" disabled={Boolean(cancellingId)} onClick={() => setPendingCancellation(null)} type="button">Keep Booking</button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
