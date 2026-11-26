import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "./App";
import { TOKEN_STORAGE_KEY } from "./api";

const TOKEN = "test-access-token";
const SPORT_ID = "b295b65a-453c-455e-96bb-ad24cb34b20e";
const COURT_ID = "66313b02-1af9-41e2-ae65-86b50fc707e9";
const EQUIPMENT_ID = "f1d8d629-c360-432c-98d7-c5f51736a130";
const BALL_ID = "8a266b22-4582-42f3-aa91-250af6179cc1";
const BOOKING_ID = "e9c8b7fd-0190-4304-b222-9b813bc40c6c";

function jsonResponse(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(data),
  };
}

function studentProfile() {
  return {
    user_id: "b2e59b8c-fb0f-41cc-9a5f-31be4b42b6cd",
    student_name: "Test Student",
    usn: "1AB23CS001",
    college_email: "student@example.edu",
    phone_number: "9876543210",
    branch: "Computer Science",
    role: "STUDENT",
  };
}

function bookingRecord(equipment = [{ equipment_id: EQUIPMENT_ID, quantity: 2 }]) {
  return {
    booking_id: BOOKING_ID,
    court_id: COURT_ID,
    booking_date: "2027-01-03",
    start_time: "15:30:00",
    end_time: "16:30:00",
    status: "BOOKED",
    equipment,
  };
}

function authenticatedFetch({
  onCreateBooking,
  bookings = [],
  catalogEquipment = [{ equipment_id: EQUIPMENT_ID, name: "Racket" }],
  availability,
} = {}) {
  const fetchMock = vi.fn(async (url, options = {}) => {
    const method = options.method || "GET";
    if (url === "/api/auth/me") return jsonResponse(studentProfile());
    if (url === "/api/catalog/sports") {
      return jsonResponse([{ sport_id: SPORT_ID, name: "Badminton" }]);
    }
    if (url === `/api/catalog/sports/${SPORT_ID}/courts`) {
      return jsonResponse([{ court_id: COURT_ID, name: "Court A" }]);
    }
    if (url === "/api/catalog/equipment") {
      return jsonResponse(catalogEquipment);
    }
    if (url.startsWith(`/api/courts/${COURT_ID}/availability`)) {
      return jsonResponse(availability || {
        court_id: COURT_ID,
        reference_date: "2027-01-03",
        timezone: "Asia/Kolkata",
        opening_time: "06:00:00",
        closing_time: "20:00:00",
        days: [
          {
            date: "2027-01-03",
            intervals: [
              { start_time: "06:00:00", end_time: "09:12:00", status: "FREE" },
              { start_time: "09:12:00", end_time: "09:27:00", status: "BOOKED", is_mine: true, reference_id: BOOKING_ID },
              { start_time: "09:27:00", end_time: "10:07:00", status: "BLOCKED", reference_id: "block-id" },
              { start_time: "10:07:00", end_time: "20:00:00", status: "FREE" },
            ],
          },
        ],
      });
    }
    if (url === "/api/bookings" && method === "GET") {
      return jsonResponse(bookings);
    }
    if (url === "/api/bookings" && method === "POST") {
      return onCreateBooking
        ? onCreateBooking(JSON.parse(options.body), options)
        : jsonResponse(bookingRecord(), 201);
    }
    if (url === `/api/bookings/${BOOKING_ID}` && method === "DELETE") {
      return jsonResponse({ ...bookingRecord(), status: "CANCELLED" });
    }
    return jsonResponse({ detail: `Unexpected test request: ${method} ${url}` }, 500);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

async function fillBookingForm(user, { equipment = true } = {}) {
  await user.selectOptions(screen.getByLabelText("Sport"), SPORT_ID);
  await screen.findByRole("option", { name: "Court A" });
  await user.selectOptions(screen.getByLabelText("Court"), COURT_ID);
  fireEvent.change(screen.getByLabelText("Booking date"), {
    target: { value: "2027-01-03" },
  });
  fireEvent.change(screen.getByLabelText("Start time · Asia/Kolkata"), {
    target: { value: "15:30" },
  });
  fireEvent.change(screen.getByLabelText("End time · Asia/Kolkata"), {
    target: { value: "16:30" },
  });
  if (equipment) {
    await user.click(screen.getByRole("checkbox", { name: "Racket" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Quantity for Racket" }), {
      target: { value: "2" },
    });
  }
}

beforeEach(() => {
  window.sessionStorage.setItem(TOKEN_STORAGE_KEY, TOKEN);
});

afterEach(() => {
  window.sessionStorage.clear();
});

describe("student frontend workflow", () => {
  it("sends the registration contract and routes to login without creating a session", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async () => jsonResponse({ user_id: "registered-id" }, 201));
    vi.stubGlobal("fetch", fetchMock);
    window.sessionStorage.clear();
    renderAt("/register");

    expect(
      Array.from(document.querySelectorAll(".registration-card form .field > span"))
        .map((label) => label.textContent),
    ).toEqual([
      "Name",
      "Email",
      "USN",
      "Phone Number",
      "Branch",
      "Password",
      "Confirm Password",
    ]);
    expect(
      document.querySelectorAll(".registration-card form .field").length,
    ).toBe(7);

    await user.type(screen.getByLabelText("Name"), "Test Student");
    await user.type(screen.getByLabelText("Email"), "Student@Example.edu");
    await user.type(screen.getByLabelText("USN"), "1AB23CS001");
    await user.type(screen.getByLabelText("Phone Number"), "9876543210");
    await user.type(screen.getByLabelText("Branch"), "Computer Science");
    await user.type(screen.getByLabelText("Password"), "strong-password");
    await user.type(screen.getByLabelText("Confirm Password"), "strong-password");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Account created");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      student_name: "Test Student",
      usn: "1AB23CS001",
      password: "strong-password",
      confirm_password: "strong-password",
      college_email: "student@example.edu",
      phone_number: "9876543210",
      branch: "Computer Science",
    });
    expect(window.sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
  });

  it("stores the login token and uses it for profile and catalog requests", async () => {
    const user = userEvent.setup();
    window.sessionStorage.clear();
    const fetchMock = vi.fn(async (url, options = {}) => {
      if (url === "/api/auth/login") {
        return jsonResponse({ access_token: TOKEN, token_type: "bearer", expires_in: 1800 });
      }
      if (url === "/api/auth/me") return jsonResponse(studentProfile());
      if (url === "/api/catalog/sports") return jsonResponse([]);
      if (url === "/api/catalog/equipment") return jsonResponse([]);
      if (url.startsWith("/api/courts/")) return jsonResponse({
        court_id: "00000000-0000-0000-0000-000000000000",
        reference_date: "2027-01-03",
        timezone: "Asia/Kolkata",
        opening_time: "06:00:00",
        closing_time: "20:00:00",
        days: [],
      });
      return jsonResponse({ detail: "Not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderAt("/login");

    await user.type(screen.getByLabelText("USN or college email"), "1AB23CS001");
    await user.type(screen.getByLabelText("Password"), "strong-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const menuButton = await screen.findByRole("button", { name: "Open navigation" });
    expect(menuButton).toHaveAttribute("aria-expanded", "false");
    await user.click(menuButton);
    expect(menuButton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Explore" })).toBeInTheDocument();
    expect(window.sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBe(TOKEN);
    const profileCall = fetchMock.mock.calls.find(([url]) => url === "/api/auth/me");
    const sportsCall = fetchMock.mock.calls.find(([url]) => url === "/api/catalog/sports");
    expect(profileCall[1].headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(sportsCall[1].headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      identifier: "1AB23CS001",
      password: "strong-password",
    });
  });

  it("loads catalog selections and submits the backend booking shape", async () => {
    const user = userEvent.setup();
    const fetchMock = authenticatedFetch();
    renderAt("/court-booking");
    await screen.findByRole("heading", { name: "Make Your Booking Now" });
    await fillBookingForm(user);
    await user.click(screen.getByRole("button", { name: "Submit booking request" }));
    await screen.findByRole("heading", { name: "Review your booking" });
    await user.click(screen.getByRole("button", { name: "Confirm Booking" }));

    expect(await screen.findByRole("heading", { name: "You’re all set." })).toBeInTheDocument();
    expect(screen.getByText("Court A")).toBeInTheDocument();
    expect(screen.getByText("BOOKED")).toBeInTheDocument();
    expect(screen.getByText("Racket")).toBeInTheDocument();
    const bookingCall = fetchMock.mock.calls.find(
      ([url, options]) => url === "/api/bookings" && options.method === "POST",
    );
    expect(JSON.parse(bookingCall[1].body)).toEqual({
      court_id: COURT_ID,
      booking_date: "2027-01-03",
      start_time: "15:30",
      end_time: "16:30",
      equipment: [{ equipment_id: EQUIPMENT_ID, quantity: 2 }],
    });
    expect(bookingCall[1].headers.Authorization).toBe(`Bearer ${TOKEN}`);
  });

  it("renders seven real availability days and supports arbitrary free intervals", async () => {
    const user = userEvent.setup();
    const days = Array.from({ length: 7 }, (_, offset) => {
      const date = new Date(Date.UTC(2027, 0, 3 + offset, 12));
      return {
        date: date.toISOString().slice(0, 10),
        intervals: [
          { start_time: "06:00:00", end_time: "09:12:00", status: "FREE" },
          { start_time: "09:12:00", end_time: "09:27:00", status: "BOOKED", is_mine: true, reference_id: BOOKING_ID },
          { start_time: "09:27:00", end_time: "10:07:00", status: "BLOCKED", reference_id: "block-id" },
          { start_time: "10:07:00", end_time: "20:00:00", status: "FREE" },
        ],
      };
    });
    authenticatedFetch({
      availability: {
        court_id: COURT_ID,
        reference_date: "2027-01-03",
        timezone: "Asia/Kolkata",
        opening_time: "06:00:00",
        closing_time: "20:00:00",
        days,
      },
    });
    renderAt("/court-booking");
    await screen.findByRole("heading", { name: "Make Your Booking Now" });

    await user.selectOptions(screen.getByLabelText("Sport"), SPORT_ID);
    await screen.findByRole("option", { name: "Court A" });
    await user.selectOptions(screen.getByLabelText("Court"), COURT_ID);

    expect(await screen.findByText("Seven-day availability")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/My booking:/).length).toBeGreaterThanOrEqual(7);
    expect(screen.getAllByLabelText(/BLOCKED:/).length).toBeGreaterThanOrEqual(7);
    expect(screen.getAllByText(/06:00 – 09:12/).length).toBeGreaterThanOrEqual(7);
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Seven-day availability")).toBeInTheDocument();
  });

  it("shows all shortages and resubmits the unchanged equipment with the continue decision", async () => {
    const user = userEvent.setup();
    let postCount = 0;
    const catalogEquipment = [
      { equipment_id: EQUIPMENT_ID, name: "Racket" },
      { equipment_id: BALL_ID, name: "Tennis balls" },
    ];
    const shortage = {
      code: "EQUIPMENT_DECISION_REQUIRED",
      message: "Choose whether to continue without unavailable equipment or cancel.",
      shortages: [
        {
          equipment_id: EQUIPMENT_ID,
          requested_quantity: 2,
          available_quantity: 1,
        },
        {
          equipment_id: BALL_ID,
          requested_quantity: 4,
          available_quantity: 0,
        },
      ],
      permitted_decisions: ["CONTINUE_WITHOUT_EQUIPMENT", "CANCEL_REQUEST"],
    };
    const fetchMock = authenticatedFetch({
      catalogEquipment,
      onCreateBooking: () => {
        postCount += 1;
        return postCount === 1
          ? jsonResponse(shortage, 409)
          : jsonResponse(bookingRecord([]), 201);
      },
    });
    renderAt("/court-booking");
    await screen.findByRole("heading", { name: "Make Your Booking Now" });
    await fillBookingForm(user);
    await user.click(screen.getByRole("checkbox", { name: "Tennis balls" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Quantity for Tennis balls" }), {
      target: { value: "4" },
    });
    await user.click(screen.getByRole("button", { name: "Submit booking request" }));
    await screen.findByRole("heading", { name: "Review your booking" });
    await user.click(screen.getByRole("button", { name: "Confirm Booking" }));

    expect(await screen.findByRole("dialog")).toHaveTextContent("Racket");
    expect(screen.getByRole("dialog")).toHaveTextContent("Tennis balls");
    expect(screen.getByRole("dialog")).toHaveTextContent("Requested 2");
    expect(screen.getByRole("dialog")).toHaveTextContent("Requested 4");
    expect(screen.getByRole("dialog")).toHaveTextContent("1 available");
    expect(screen.getByRole("dialog")).toHaveTextContent("0 available");
    await user.click(screen.getByRole("button", { name: "Continue without unavailable equipment" }));
    expect(await screen.findByRole("heading", { name: "You’re all set." })).toBeInTheDocument();

    const posts = fetchMock.mock.calls.filter(
      ([url, options]) => url === "/api/bookings" && options.method === "POST",
    );
    expect(posts).toHaveLength(2);
    const initialRequest = JSON.parse(posts[0][1].body);
    const continuedRequest = JSON.parse(posts[1][1].body);
    expect(continuedRequest).toEqual({
      ...initialRequest,
      equipment_decision: "CONTINUE_WITHOUT_EQUIPMENT",
    });
    expect(continuedRequest.equipment).toEqual([
      { equipment_id: EQUIPMENT_ID, quantity: 2 },
      { equipment_id: BALL_ID, quantity: 4 },
    ]);
  });

  it("cancels the shortage request locally without another booking call or confirmation", async () => {
    const user = userEvent.setup();
    const fetchMock = authenticatedFetch({
      onCreateBooking: () => jsonResponse({
        code: "EQUIPMENT_DECISION_REQUIRED",
        shortages: [{
          equipment_id: EQUIPMENT_ID,
          requested_quantity: 2,
          available_quantity: 0,
        }],
      }, 409),
    });
    renderAt("/court-booking");
    await screen.findByRole("heading", { name: "Make Your Booking Now" });
    await fillBookingForm(user);
    await user.click(screen.getByRole("button", { name: "Submit booking request" }));
    await screen.findByRole("heading", { name: "Review your booking" });
    await user.click(screen.getByRole("button", { name: "Confirm Booking" }));
    await screen.findByRole("dialog");
    await user.click(screen.getByRole("button", { name: "Cancel request" }));

    expect(screen.getByRole("status")).toHaveTextContent("No booking created");
    expect(screen.queryByText("Booking confirmed")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(
      ([url, options]) => url === "/api/bookings" && options.method === "POST",
    )).toHaveLength(1);
  });

  it("reports E3 equipment-capacity conflicts separately from shortage decisions", async () => {
    const user = userEvent.setup();
    let postCount = 0;
    authenticatedFetch({
      onCreateBooking: () => {
        postCount += 1;
        if (postCount === 1) {
          return jsonResponse({
            code: "EQUIPMENT_DECISION_REQUIRED",
            shortages: [{
              equipment_id: EQUIPMENT_ID,
              requested_quantity: 2,
              available_quantity: 1,
            }],
          }, 409);
        }
        return jsonResponse({
          detail: {
            code: "equipment_unavailable",
            equipment_id: EQUIPMENT_ID,
            requested_quantity: 2,
            available_quantity: 0,
          },
        }, 409);
      },
    });
    renderAt("/court-booking");
    await screen.findByRole("heading", { name: "Make Your Booking Now" });
    await fillBookingForm(user);
    await user.click(screen.getByRole("button", { name: "Submit booking request" }));
    await screen.findByRole("heading", { name: "Review your booking" });
    await user.click(screen.getByRole("button", { name: "Confirm Booking" }));
    await screen.findByRole("dialog");
    await user.click(screen.getByRole("button", { name: "Continue without unavailable equipment" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Equipment availability changed. 2 requested, 0 currently available.",
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("treats the backend 200 booking_created false response as no booking", async () => {
    const user = userEvent.setup();
    const fetchMock = authenticatedFetch({
      onCreateBooking: () => jsonResponse({
        code: "BOOKING_NOT_CREATED",
        booking_created: false,
        request_cancelled: true,
        message: "Request cancelled; no booking was created.",
      }, 200),
    });
    renderAt("/court-booking");
    await screen.findByRole("heading", { name: "Make Your Booking Now" });
    await fillBookingForm(user, { equipment: false });
    await user.click(screen.getByRole("button", { name: "Submit booking request" }));
    await screen.findByRole("heading", { name: "Review your booking" });
    await user.click(screen.getByRole("button", { name: "Confirm Booking" }));

    expect(await screen.findByRole("status")).toHaveTextContent("No booking created");
    expect(screen.queryByText("Booking confirmed")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(
      ([url, options]) => url === "/api/bookings" && options.method === "POST",
    )).toHaveLength(1);
  });

  it("shows a committed booking warning instead of reporting failure after cache refresh errors", async () => {
    const user = userEvent.setup();
    authenticatedFetch({
      onCreateBooking: () => jsonResponse({
        detail: {
          code: "booking_committed_refresh_failed",
          booking_id: BOOKING_ID,
          committed: true,
        },
      }, 503),
    });
    renderAt("/court-booking");
    await screen.findByRole("heading", { name: "Make Your Booking Now" });
    await fillBookingForm(user, { equipment: false });
    await user.click(screen.getByRole("button", { name: "Submit booking request" }));
    await screen.findByRole("heading", { name: "Review your booking" });
    await user.click(screen.getByRole("button", { name: "Confirm Booking" }));

    expect(await screen.findByText(/Your booking was committed/i)).toBeInTheDocument();
    expect(screen.getByText(BOOKING_ID)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("loads booking history and updates a booking after confirmed cancellation", async () => {
    const user = userEvent.setup();
    const futureBooking = {
      ...bookingRecord(),
      booking_date: "2099-01-03",
      start_time: "15:30:00",
      end_time: "16:30:00",
    };
    const fetchMock = authenticatedFetch({ bookings: [futureBooking] });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderAt("/bookings");

    expect(await screen.findByText(BOOKING_ID)).toBeInTheDocument();
    expect(screen.getByText("Court A")).toBeInTheDocument();
    expect(screen.getByText("Racket")).toBeInTheDocument();
    const bookingCard = screen.getByText(BOOKING_ID).closest("article");
    expect(within(bookingCard).getByText("BOOKED")).toBeInTheDocument();
    await user.click(within(bookingCard).getByRole("button", { name: "Cancel booking" }));
    await user.click(screen.getByRole("button", { name: "Cancel Booking" }));

    expect(await screen.findByRole("status")).toHaveTextContent("was cancelled");
    await user.click(screen.getByRole("button", { name: "Cancelled" }));
    const cancelledCard = screen.getByText(BOOKING_ID).closest("article");
    expect(within(cancelledCard).getByText("CANCELLED")).toBeInTheDocument();
    expect(within(cancelledCard).queryByRole("button", { name: "Cancel booking" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(
      ([url, options]) => url === `/api/bookings/${BOOKING_ID}` && options.method === "DELETE",
    )).toBe(true);
  });

  it("clears an expired session and redirects to sign in", async () => {
    window.sessionStorage.setItem(TOKEN_STORAGE_KEY, TOKEN);
    const fetchMock = vi.fn(async () =>
      jsonResponse({ detail: "Invalid or expired access token" }, 401),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderAt("/");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(window.sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
  });

  it("shows network errors on login without hiding the failure", async () => {
    const user = userEvent.setup();
    window.sessionStorage.clear();
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("fetch failed");
    }));
    renderAt("/login");
    await user.type(screen.getByLabelText("USN or college email"), "1AB23CS001");
    await user.type(screen.getByLabelText("Password"), "strong-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to reach the booking service");
  });
});
