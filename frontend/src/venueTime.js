const VENUE_TIME_ZONE = "Asia/Kolkata";

function getVenueDateTimeParts(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: VENUE_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  return Object.fromEntries(
    parts
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value]),
  );
}

export function getVenueDate(now = new Date()) {
  const parts = getVenueDateTimeParts(now);
  return `${parts.year}-${parts.month}-${parts.day}`;
}

export function isBookingCancelable(booking, now = new Date()) {
  if (booking.status !== "BOOKED") {
    return false;
  }
  const parts = getVenueDateTimeParts(now);
  const currentMinute = `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
  const bookingMinute = `${booking.booking_date}T${booking.start_time.slice(0, 5)}`;
  return bookingMinute > currentMinute;
}

export function formatVenueDate(dateValue) {
  const [year, month, day] = dateValue.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day, 12));
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: VENUE_TIME_ZONE,
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function formatBookingTime(timeValue) {
  return timeValue.slice(0, 5);
}
