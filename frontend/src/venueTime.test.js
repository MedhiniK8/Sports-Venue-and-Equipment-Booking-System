import { describe, expect, it } from "vitest";
import { formatBookingTime, formatVenueDate, getVenueDate, isBookingCancelable } from "./venueTime";

describe("venue-local time helpers", () => {
  it("derives calendar dates using Asia/Kolkata rather than the browser timezone", () => {
    const instant = new Date("2026-11-24T20:00:00.000Z");
    expect(getVenueDate(instant)).toBe("2026-11-25");
    expect(formatVenueDate("2026-11-25")).toContain("25");
    expect(formatBookingTime("06:30:00")).toBe("06:30");
  });

  it("shows cancellation only for booked intervals strictly after venue-local now", () => {
    const now = new Date("2026-11-25T09:32:38.000Z");
    expect(isBookingCancelable({
      status: "BOOKED",
      booking_date: "2026-11-25",
      start_time: "15:03:00",
    }, now)).toBe(true);
    expect(isBookingCancelable({
      status: "BOOKED",
      booking_date: "2026-11-25",
      start_time: "15:02:00",
    }, now)).toBe(false);
    expect(isBookingCancelable({
      status: "CANCELLED",
      booking_date: "2026-11-26",
      start_time: "10:00:00",
    }, now)).toBe(false);
  });
});
